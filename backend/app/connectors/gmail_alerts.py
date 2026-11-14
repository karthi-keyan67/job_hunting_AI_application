from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
import base64
from html import unescape
import re

import httpx

from bs4 import BeautifulSoup

from app.connectors.base import ConnectorError, ConnectorNotConfigured, JobConnector


class GmailJobAlertConnector(JobConnector):
    """Read-only Gmail alert connector with a per-user OAuth connection."""

    def __init__(self, source, session=None):
        super().__init__(source)
        self.session = session
        self.allowed_senders = self.source.configuration.get("allowed_senders", [])

    @staticmethod
    def normalize_sender_allowlist(value) -> list[str]:
        if not isinstance(value, list) or not value or len(value) > 50:
            raise ConnectorNotConfigured("Configure an allowlist of Gmail alert sender addresses")
        if any(not isinstance(sender, str) or not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", sender.strip()) for sender in value):
            raise ConnectorNotConfigured("Gmail sender allowlist contains an invalid address")
        return sorted({sender.strip().casefold() for sender in value})

    def validate_configuration(self) -> None:
        from app.core.config import get_settings

        settings = get_settings()
        if not self.session or not self.source.user_id:
            raise ConnectorNotConfigured("Gmail collection requires an owned user source")
        if not (settings.google_oauth_client_id and settings.google_oauth_client_secret and settings.google_oauth_redirect_uri and settings.oauth_token_encryption_key):
            raise ConnectorNotConfigured("Gmail OAuth credentials are not configured")
        self.allowed_senders = self.normalize_sender_allowlist(self.allowed_senders)
        terms = self.source.configuration.get("required_terms", [])
        if not isinstance(terms, list) or len(terms) > 50 or any(not isinstance(term, str) or not term.strip() or len(term) > 100 for term in terms):
            raise ConnectorNotConfigured("Gmail required terms must be a short list of text values")

    async def fetch_jobs(self) -> list[dict]:
        self.validate_configuration()
        from app.services.google_oauth import GoogleOAuthService

        token = await GoogleOAuthService(self.session).access_token(self.source.user_id)
        if not token:
            raise ConnectorNotConfigured("Connect Gmail using the authorized OAuth flow before collection")
        senders = sorted({sender.casefold() for sender in self.allowed_senders})
        query = "{" + " ".join(f"from:{sender}" for sender in senders) + "} newer_than:30d"
        headers = {"Authorization": f"Bearer {token}"}
        api = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                listing = await client.get(api, headers=headers, params={"q": query, "maxResults": 50})
                if listing.status_code == 401:
                    raise ConnectorNotConfigured("Gmail access was revoked or expired; reconnect the account")
                if listing.status_code != 200:
                    raise ConnectorError("Gmail message listing failed")
                message_ids = [row["id"] for row in listing.json().get("messages", []) if isinstance(row, dict) and isinstance(row.get("id"), str)]
                results = []
                required_terms = self.source.configuration.get("required_terms", [])
                for message_id in message_ids[:50]:
                    response = await client.get(f"{api}/{message_id}", headers=headers, params={"format": "raw"})
                    if response.status_code != 200:
                        continue
                    encoded = response.json().get("raw")
                    if not isinstance(encoded, str):
                        continue
                    try:
                        raw_message = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
                    except (ValueError, base64.binascii.Error):
                        continue
                    results.extend(self.parse_message(raw_message, self.allowed_senders, required_terms))
                return results
        except httpx.HTTPError as exc:
            raise ConnectorError("Gmail API request failed") from exc

    @staticmethod
    def parse_message(raw_message: bytes, allowed_senders: list[str] | None = None, required_terms: list[str] | None = None) -> list[dict]:
        message = BytesParser(policy=policy.default).parsebytes(raw_message)
        sender = parseaddr(message.get("From", ""))[1].casefold()
        allowlist = {value.casefold() for value in (allowed_senders or [])}
        if not allowlist or sender not in allowlist:
            return []
        parts: list[str] = []
        links: list[str] = []
        if message.is_multipart():
            payloads = [part for part in message.walk() if part.get_content_type() in {"text/plain", "text/html"}]
        else:
            payloads = [message]
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
        title = message.get("Subject", "")
        haystack = f"{title} {body_text}".casefold()
        if required_terms and not any(term.casefold() in haystack for term in required_terms):
            return []
        link = next((url for url in links if url.startswith(("https://", "http://"))), None)
        if not link:
            match = re.search(r"https?://[^\s<>\"']+", body_text)
            link = match.group(0).rstrip(".,)") if match else None
        if not link:
            return []
        # Keep extraction conservative; do not infer fields that were not present in the alert.
        company_match = re.search(r"(?:company|at)\s*[:\-]?\s*(.{2,100}?)(?=\s+location\s*[:\-]|$)", body_text, re.I)
        location_match = re.search(r"(?:location|based in)\s*[:\-]?\s*(.{2,100}?)(?=\s+view\s+job|\s+https?://|$)", body_text, re.I)
        return [{"external_id": message.get("Message-ID") or link, "title": title[:300] or "Job alert",
                 "company_name": company_match.group(1).strip() if company_match else "Unknown company",
                 "location": location_match.group(1).strip() if location_match else None,
                 "description": body_text[:100_000], "job_url": link, "apply_url": link,
                 "raw_data": {"message_id": message.get("Message-ID"), "sender": sender}}]
