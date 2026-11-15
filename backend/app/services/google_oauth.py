import asyncio
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from sqlalchemy import select

from app.core.config import get_settings
from app.models.enums import JobSourceStatus
from app.models.jobs import JobSource
from app.repositories.google_oauth import GoogleOAuthRepository
from app.repositories.portal_connections import record_integration_event

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URI = "https://oauth2.googleapis.com/revoke"
GOOGLE_OAUTH_CALLBACK_PATH = "/api/v1/integrations/gmail/callback"


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class GoogleOAuthService:
    def __init__(self, session):
        self.session = session
        self.repository = GoogleOAuthRepository(session)
        self.settings = get_settings()

    def configuration_issues(self) -> list[str]:
        """Return safe, actionable configuration categories without exposing values."""
        issues: list[str] = []
        required = (
            ("google_oauth_client_id", "GOOGLE_OAUTH_CLIENT_ID (Google OAuth client ID)"),
            ("google_oauth_client_secret", "GOOGLE_OAUTH_CLIENT_SECRET (Google OAuth client secret)"),
            ("google_oauth_redirect_uri", "GOOGLE_OAUTH_REDIRECT_URI (HTTPS callback URI)"),
            ("oauth_token_encryption_key", "OAUTH_TOKEN_ENCRYPTION_KEY (token encryption key)"),
        )
        for attribute, label in required:
            value = getattr(self.settings, attribute, None)
            if not isinstance(value, str) or not value.strip():
                issues.append(label)

        redirect_uri = getattr(self.settings, "google_oauth_redirect_uri", None)
        if isinstance(redirect_uri, str) and redirect_uri.strip():
            try:
                parsed = urlsplit(redirect_uri)
                port = parsed.port
                valid_redirect = (
                    parsed.scheme == "https"
                    and bool(parsed.hostname)
                    and (port is None or 1 <= port <= 65535)
                    and parsed.username is None
                    and parsed.password is None
                    and parsed.path == GOOGLE_OAUTH_CALLBACK_PATH
                    and not parsed.query
                    and not parsed.fragment
                )
            except ValueError:
                valid_redirect = False
            if not valid_redirect:
                issues.append(
                    "GOOGLE_OAUTH_REDIRECT_URI must be a valid HTTPS URL ending in "
                    f"{GOOGLE_OAUTH_CALLBACK_PATH} with no query or fragment"
                )

        encryption_key = getattr(self.settings, "oauth_token_encryption_key", None)
        if isinstance(encryption_key, str) and encryption_key.strip():
            try:
                Fernet(encryption_key.encode("ascii"))
            except (ValueError, UnicodeEncodeError):
                issues.append("OAUTH_TOKEN_ENCRYPTION_KEY must be a valid Fernet key")
        return issues

    def configuration_status(self) -> dict[str, str | bool | None]:
        issues = self.configuration_issues()
        return {
            "oauth_configured": not issues,
            "oauth_configuration_message": (
                "Gmail connection is unavailable. Configure: " + "; ".join(issues) + "."
                if issues else None
            ),
        }

    def _fernet(self) -> Fernet:
        key = self.settings.oauth_token_encryption_key
        try:
            if not key:
                raise ValueError("missing key")
            return Fernet(key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            issues = self.configuration_issues()
            message = "Gmail connection is unavailable. Configure: " + "; ".join(issues) + "."
            raise HTTPException(status_code=503, detail=message) from exc

    def _client_config(self) -> dict:
        issues = self.configuration_issues()
        if issues:
            message = "Gmail connection is unavailable. Configure: " + "; ".join(issues) + "."
            raise HTTPException(status_code=503, detail=message)
        return {
            "web": {
                "client_id": self.settings.google_oauth_client_id,
                "client_secret": self.settings.google_oauth_client_secret,
                "auth_uri": GOOGLE_AUTH_URI,
                "token_uri": GOOGLE_TOKEN_URI,
                "redirect_uris": [self.settings.google_oauth_redirect_uri],
            }
        }

    async def _disable_alert_sources(self, user_id: UUID, *, reason: str) -> None:
        rows = await self.session.scalars(select(JobSource).where(
            JobSource.user_id == user_id, JobSource.source_type == "GMAIL_ALERT", JobSource.is_enabled.is_(True)
        ))
        for source in rows:
            source.is_enabled = False
            source.status = JobSourceStatus.DISABLED
            platform = str((source.configuration or {}).get("platform", "GENERIC")).upper()
            record_integration_event(self.session, user_id, platform, "DISCOVERY_DISABLED",
                                     source_id=source.id, details={"enabled": False, "reason": reason})

    async def authorize(self, user_id: UUID) -> dict[str, str]:
        client_config = self._client_config()
        self._fernet()
        state = secrets.token_urlsafe(32)
        await self.repository.add_state(user_id, hashlib.sha256(state.encode()).hexdigest(), datetime.now(UTC) + timedelta(minutes=10))
        await self.session.commit()
        flow = Flow.from_client_config(client_config, scopes=[GMAIL_READONLY_SCOPE], state=state)
        flow.redirect_uri = self.settings.google_oauth_redirect_uri
        authorization_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        return {"authorization_url": authorization_url, "expires_in": 600}

    async def callback(self, state: str | None, code: str | None, provider_error: str | None = None) -> dict[str, str | bool]:
        if not state or len(state) > 512:
            raise HTTPException(status_code=400, detail="Invalid OAuth state")
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        record = await self.repository.get_state(state_hash, lock=True)
        now = datetime.now(UTC)
        if record is None or record.consumed_at is not None:
            await self.session.rollback()
            raise HTTPException(status_code=400, detail="Invalid or already used OAuth state")
        expires_at = record.expires_at if record.expires_at.tzinfo else record.expires_at.replace(tzinfo=UTC)
        if expires_at <= now:
            await self.session.rollback()
            raise HTTPException(status_code=400, detail="OAuth state has expired")
        record.consumed_at = now
        user_id = record.user_id
        await self.session.commit()
        if provider_error:
            raise HTTPException(status_code=400, detail="Gmail authorization was not granted")
        if not code or len(code) > 4096:
            raise HTTPException(status_code=400, detail="OAuth authorization code is missing")

        config = self._client_config()
        flow = Flow.from_client_config(config, scopes=[GMAIL_READONLY_SCOPE], state=state)
        flow.redirect_uri = self.settings.google_oauth_redirect_uri
        try:
            await asyncio.to_thread(flow.fetch_token, code=code)
            credentials = flow.credentials
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Gmail authorization could not be completed") from exc

        granted = list(credentials.scopes or [])
        if GMAIL_READONLY_SCOPE not in granted or not credentials.refresh_token:
            raise HTTPException(status_code=400, detail="Gmail did not grant the required offline read-only access")
        try:
            encrypted = self._fernet().encrypt(credentials.to_json().encode("utf-8")).decode("ascii")
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Gmail credentials could not be stored securely") from exc
        await self.repository.save_connection(user_id, encrypted, granted, _aware_utc(credentials.expiry))
        record_integration_event(self.session, user_id, "GMAIL", "ACCOUNT_CONNECTED",
                                 details={"scope": GMAIL_READONLY_SCOPE})
        await self.session.commit()
        return {"connected": True, "detail": "Gmail read-only access connected"}

    async def status(self, user_id: UUID) -> dict:
        record = await self.repository.get_connection(user_id)
        configuration = self.configuration_status()
        if record is None or record.revoked_at is not None:
            return {"connected": False, "gmail_address": None, "scopes": [], **configuration}
        return {"connected": True, "gmail_address": record.gmail_address, "scopes": record.scopes, "expires_at": record.expires_at, **configuration}

    async def access_token(self, user_id: UUID) -> str | None:
        record = await self.repository.get_connection(user_id, lock=True)
        if record is None or record.revoked_at is not None:
            return None
        try:
            serialized = self._fernet().decrypt(record.encrypted_credentials.encode("ascii"))
            credentials = Credentials.from_authorized_user_info(json.loads(serialized), scopes=[GMAIL_READONLY_SCOPE])
        except (InvalidToken, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=503, detail="Stored Gmail authorization is unavailable; reconnect the account") from exc
        if credentials.expired:
            if not credentials.refresh_token:
                record.revoked_at = datetime.now(UTC)
                record.encrypted_credentials = ""
                await self._disable_alert_sources(user_id, reason="gmail_reauthorization_required")
                record_integration_event(self.session, user_id, "GMAIL", "ACCOUNT_REAUTH_REQUIRED")
                await self.session.commit()
                raise HTTPException(status_code=401, detail="Gmail authorization expired; reconnect the account")
            try:
                await asyncio.to_thread(credentials.refresh, GoogleRequest())
            except Exception as exc:
                record.revoked_at = datetime.now(UTC)
                record.encrypted_credentials = ""
                await self._disable_alert_sources(user_id, reason="gmail_refresh_failed")
                record_integration_event(self.session, user_id, "GMAIL", "ACCOUNT_REAUTH_REQUIRED")
                await self.session.commit()
                raise HTTPException(status_code=401, detail="Gmail authorization expired; reconnect the account") from exc
            record.encrypted_credentials = self._fernet().encrypt(credentials.to_json().encode()).decode("ascii")
            record.expires_at = _aware_utc(credentials.expiry)
            await self.session.commit()
        return credentials.token

    async def revoke(self, user_id: UUID) -> None:
        record = await self.repository.get_connection(user_id, lock=True)
        if record is None or record.revoked_at is not None:
            return
        try:
            serialized = self._fernet().decrypt(record.encrypted_credentials.encode("ascii"))
            credentials = Credentials.from_authorized_user_info(json.loads(serialized), scopes=[GMAIL_READONLY_SCOPE])
        except (InvalidToken, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=503, detail="Stored Gmail authorization is unavailable") from exc
        token_to_revoke = credentials.refresh_token or credentials.token
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                response = await client.post(GOOGLE_REVOKE_URI, data={"token": token_to_revoke})
            if response.status_code not in {200, 400}:
                raise HTTPException(status_code=502, detail="Google did not confirm credential revocation")
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="Google credential revocation is temporarily unavailable") from exc
        record.revoked_at = datetime.now(UTC)
        record.encrypted_credentials = ""
        await self._disable_alert_sources(user_id, reason="gmail_disconnected")
        record_integration_event(self.session, user_id, "GMAIL", "ACCOUNT_DISCONNECTED")
        await self.session.commit()
