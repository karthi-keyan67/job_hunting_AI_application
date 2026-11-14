import asyncio
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from app.core.config import get_settings
from app.repositories.google_oauth import GoogleOAuthRepository

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URI = "https://oauth2.googleapis.com/revoke"


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class GoogleOAuthService:
    def __init__(self, session):
        self.session = session
        self.repository = GoogleOAuthRepository(session)
        self.settings = get_settings()

    def _fernet(self) -> Fernet:
        key = self.settings.oauth_token_encryption_key
        if not key:
            raise HTTPException(status_code=503, detail="Gmail OAuth is not configured")
        try:
            return Fernet(key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise HTTPException(status_code=503, detail="Gmail token encryption is not configured correctly") from exc

    def _client_config(self) -> dict:
        if not (self.settings.google_oauth_client_id and self.settings.google_oauth_client_secret and self.settings.google_oauth_redirect_uri):
            raise HTTPException(status_code=503, detail="Gmail OAuth is not configured")
        if not self.settings.google_oauth_redirect_uri.startswith("https://"):
            raise HTTPException(status_code=503, detail="Gmail OAuth requires an HTTPS callback")
        return {
            "web": {
                "client_id": self.settings.google_oauth_client_id,
                "client_secret": self.settings.google_oauth_client_secret,
                "auth_uri": GOOGLE_AUTH_URI,
                "token_uri": GOOGLE_TOKEN_URI,
                "redirect_uris": [self.settings.google_oauth_redirect_uri],
            }
        }

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
        await self.session.commit()
        return {"connected": True, "detail": "Gmail read-only access connected"}

    async def status(self, user_id: UUID) -> dict:
        record = await self.repository.get_connection(user_id)
        if record is None or record.revoked_at is not None:
            return {"connected": False, "gmail_address": None, "scopes": []}
        return {"connected": True, "gmail_address": record.gmail_address, "scopes": record.scopes, "expires_at": record.expires_at}

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
                await self.session.commit()
                raise HTTPException(status_code=401, detail="Gmail authorization expired; reconnect the account")
            try:
                await asyncio.to_thread(credentials.refresh, GoogleRequest())
            except Exception as exc:
                record.revoked_at = datetime.now(UTC)
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
        await self.session.commit()
