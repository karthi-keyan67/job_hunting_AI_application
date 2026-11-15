from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
import base64
from html import unescape
import re
from datetime import UTC, datetime

from sqlalchemy import select

import httpx

from bs4 import BeautifulSoup

from app.connectors.alert_adapters import AlertAdapterRegistry
from app.connectors.base import ConnectorError, ConnectorNotConfigured, JobConnector


class GmailJobAlertConnector(JobConnector):
    """Read-only Gmail alert connector with a per-user OAuth connection."""

    def __init__(self, source, session=None):
        super().__init__(source)
        self.session = session
        self.allowed_senders = self.source.configuration.get("allowed_senders", [])
        self.platform = str(self.source.configuration.get("platform", "GENERIC")).upper()

    @staticmethod
    def normalize_sender_allowlist(value) -> list[str]:
        if not isinstance(value, list) or not value or len(value) > 50:
            raise ConnectorNotConfigured("Configure an allowlist of Gmail alert sender addresses")
        if any(not isinstance(sender, str) or not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", sender.strip()) for sender in value):
            raise ConnectorNotConfigured("Gmail sender allowlist contains an invalid address")
        return sorted({sender.strip().casefold() for sender in value})

    @staticmethod
    def validate_source_configuration(configuration: dict) -> dict:
        config = dict(configuration)
        config["allowed_senders"] = GmailJobAlertConnector.normalize_sender_allowlist(config.get("allowed_senders"))
        platform = str(config.get("platform", "GENERIC")).upper()
        if platform not in {"GENERIC", "LINKEDIN", "NAUKRI", "INDEED", "INSTAHYRE", "CUTSHORT", "HIRIST"}:
            raise ConnectorNotConfigured("Unsupported Gmail alert platform")
        config["platform"] = platform
        terms = config.get("required_terms", [])
        labels = config.get("label_ids", [])
        if not isinstance(terms, list) or len(terms) > 50 or any(not isinstance(term, str) or not term.strip() or len(term) > 100 for term in terms):
            raise ConnectorNotConfigured("Gmail required terms must be a short list of text values")
        if not isinstance(labels, list) or len(labels) > 20 or any(not isinstance(label, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", label) for label in labels):
            raise ConnectorNotConfigured("Gmail label IDs must be a short list of valid IDs")
        return config

    def validate_configuration(self) -> None:
        from app.core.config import get_settings

        settings = get_settings()
        if not self.session or not self.source.user_id:
            raise ConnectorNotConfigured("Gmail collection requires an owned user source")
        if not (settings.google_oauth_client_id and settings.google_oauth_client_secret and settings.google_oauth_redirect_uri and settings.oauth_token_encryption_key):
            raise ConnectorNotConfigured("Gmail OAuth credentials are not configured")
        self.source.configuration = self.validate_source_configuration(self.source.configuration)
        self.allowed_senders = self.source.configuration["allowed_senders"]
        self.platform = self.source.configuration["platform"]

    @staticmethod
    def _extract(raw_message: bytes, allowed_senders: list[str], required_terms: list[str], platform: str) -> tuple[list[dict], str | None, str, str, str]:
        """Parse only the documented generic key/value format; portal formats await sanitized samples."""
        message = BytesParser(policy=policy.default).parsebytes(raw_message)
        sender = parseaddr(message.get("From", ""))[1].casefold()
        subject = str(message.get("Subject", ""))[:998]
        if sender not in {value.casefold() for value in allowed_senders}:
            return [], None, sender, subject, "Sender is not allowlisted"
        parts: list[str] = []
        links: list[str] = []
        payloads = [part for part in message.walk() if part.get_content_type() in {"text/plain", "text/html"}] if message.is_multipart() else [message]
        for part in payloads:
            try:
                body = part.get_content()
            except Exception:
                continue
            if part.get_content_type() == "text/html":
                soup = BeautifulSoup(body, "html.parser")
                links.extend(anchor.get("href") for anchor in soup.select("a[href]") if anchor.get("href"))
                parts.append(soup.get_text(" ", strip=True))
            else:
                parts.append(str(body))
        body_text = unescape(" ".join(parts))
        haystack = f"{subject} {body_text}".casefold()
        if required_terms and not any(term.casefold() in haystack for term in required_terms):
            return [], None, sender, subject, "Alert did not match configured required terms"
        try:
            extracted, reason = AlertAdapterRegistry.get(platform).parse(message, body_text, links, sender)
        except ValueError:
            return [], body_text, sender, subject, "Unsupported alert platform"
        return extracted, body_text, sender, subject, reason

    async def fetch_jobs(self) -> list[dict]:
        self.validate_configuration()
        from app.services.google_oauth import GoogleOAuthService

        token = await GoogleOAuthService(self.session).access_token(self.source.user_id)
        if not token:
            raise ConnectorNotConfigured("Connect Gmail using the authorized OAuth flow before collection")
        senders = sorted({sender.casefold() for sender in self.allowed_senders})
        cursor = int(self.source.configuration.get("last_synced_internal_date_ms", 0) or 0)
        query = "{" + " ".join(f"from:{sender}" for sender in senders) + "}"
        if cursor:
            query += f" after:{max(0, cursor // 1000 - 300)}"
        headers = {"Authorization": f"Bearer {token}"}
        api = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                results = []
                required_terms = self.source.configuration.get("required_terms", [])
                labels = self.source.configuration.get("label_ids", [])
                page_token = self.source.configuration.get("gmail_next_page_token")
                max_seen = cursor
                message_ids: list[str] = []
                for _page in range(10):
                    params = {"q": query, "maxResults": 100}
                    if labels:
                        params["labelIds"] = labels
                    if page_token:
                        params["pageToken"] = page_token
                    listing = await client.get(api, headers=headers, params=params)
                    if listing.status_code == 401:
                        raise ConnectorNotConfigured("Gmail access was revoked or expired; reconnect the account")
                    if listing.status_code != 200:
                        raise ConnectorError("Gmail message listing failed")
                    listing_json = listing.json()
                    message_ids.extend(row["id"] for row in listing_json.get("messages", []) if isinstance(row, dict) and isinstance(row.get("id"), str))
                    page_token = listing_json.get("nextPageToken")
                    if not page_token:
                        break
                from app.models.integrations import GmailAlertReview
                pending_review_ids = await self.session.scalars(select(GmailAlertReview.gmail_message_id).where(
                    GmailAlertReview.source_id == self.source.id, GmailAlertReview.status == "NEEDS_REVIEW"
                ).order_by(GmailAlertReview.updated_at.asc()).limit(100))
                message_ids.extend(pending_review_ids.all())
                for message_id in dict.fromkeys(message_ids):
                    existing = await self.session.scalar(select(GmailAlertReview).where(GmailAlertReview.source_id == self.source.id, GmailAlertReview.gmail_message_id == message_id))
                    if existing and existing.status != "NEEDS_REVIEW":
                        continue
                    if existing:
                        existing.updated_at = datetime.now(UTC)
                    response = await client.get(f"{api}/{message_id}", headers=headers, params={"format": "raw"})
                    if response.status_code != 200:
                        review = existing or GmailAlertReview(user_id=self.source.user_id, source_id=self.source.id, gmail_message_id=message_id, sender="unknown", subject="")
                        review.status, review.reason, review.excerpt = "NEEDS_REVIEW", "Gmail could not provide this message for parsing", ""
                        if existing is None:
                            self.session.add(review)
                        continue
                    encoded = response.json().get("raw")
                    if not isinstance(encoded, str):
                        review = existing or GmailAlertReview(user_id=self.source.user_id, source_id=self.source.id, gmail_message_id=message_id, sender="unknown", subject="")
                        review.status, review.reason, review.excerpt = "NEEDS_REVIEW", "Gmail returned an invalid message payload", ""
                        if existing is None:
                            self.session.add(review)
                        continue
                    try:
                        raw_message = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
                    except (ValueError, base64.binascii.Error):
                        review = existing or GmailAlertReview(user_id=self.source.user_id, source_id=self.source.id, gmail_message_id=message_id, sender="unknown", subject="")
                        review.status, review.reason, review.excerpt = "NEEDS_REVIEW", "Gmail message encoding could not be parsed", ""
                        if existing is None:
                            self.session.add(review)
                        continue
                    parsed, body_text, sender, subject, reason = self._extract(raw_message, self.allowed_senders, required_terms, self.platform)
                    internal_date = response.json().get("internalDate")
                    received_at = datetime.fromtimestamp(int(internal_date) / 1000, tz=UTC) if str(internal_date or "").isdigit() else None
                    if internal_date and str(internal_date).isdigit():
                        max_seen = max(max_seen, int(internal_date))
                    if parsed:
                        parsed[0]["posted_at"] = received_at
                        parsed[0]["external_id"] = message_id
                        results.extend(parsed)
                        review = existing or GmailAlertReview(user_id=self.source.user_id, source_id=self.source.id, gmail_message_id=message_id, sender=sender, subject=subject)
                        review.sender, review.subject, review.received_at = sender, subject, received_at
                        review.status, review.reason, review.excerpt = "IMPORTED", "Parsed and handed to the existing job ingestion pipeline", ""
                        if existing is None:
                            self.session.add(review)
                    elif reason != "Alert did not match configured required terms" and sender in set(senders):
                        review = existing or GmailAlertReview(user_id=self.source.user_id, source_id=self.source.id, gmail_message_id=message_id, sender=sender or "unknown", subject=subject)
                        review.sender, review.subject, review.received_at = sender or "unknown", subject, received_at
                        review.status, review.reason, review.excerpt = "NEEDS_REVIEW", reason, (body_text or "")[:500]
                        if existing is None:
                            self.session.add(review)
                    else:
                        # Suppress repeat processing of intentionally filtered alerts without exposing their body.
                        review = existing or GmailAlertReview(user_id=self.source.user_id, source_id=self.source.id, gmail_message_id=message_id, sender=sender or "unknown", subject=subject)
                        review.sender, review.subject, review.received_at = sender or "unknown", subject, received_at
                        review.status, review.reason, review.excerpt = "FILTERED", reason, ""
                        if existing is None:
                            self.session.add(review)
                updated_config = {**self.source.configuration}
                if page_token:
                    updated_config["gmail_next_page_token"] = page_token
                else:
                    updated_config.pop("gmail_next_page_token", None)
                    if max_seen > cursor:
                        updated_config["last_synced_internal_date_ms"] = max_seen
                self.source.configuration = updated_config
                return results
        except httpx.HTTPError as exc:
            raise ConnectorError("Gmail API request failed") from exc

    @staticmethod
    def parse_message(raw_message: bytes, allowed_senders: list[str] | None = None, required_terms: list[str] | None = None) -> list[dict]:
        parsed, _body, _sender, _subject, _reason = GmailJobAlertConnector._extract(raw_message, allowed_senders or [], required_terms or [], "GENERIC")
        return parsed
