from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from html import unescape
import re

from bs4 import BeautifulSoup

from app.connectors.base import ConnectorNotConfigured, JobConnector


class GmailJobAlertConnector(JobConnector):
    """Parser and future authorized Gmail adapter; no OAuth client is configured in this phase."""

    def validate_configuration(self) -> None:
        # A connection identifier is metadata only. Tokens are supplied by a future secret store.
        if not self.source.configuration.get("authorized_connection_id"):
            raise ConnectorNotConfigured("Gmail OAuth authorization is not configured")
        raise ConnectorNotConfigured("Gmail OAuth provider is not installed; live collection is awaiting credentials")

    async def fetch_jobs(self) -> list[dict]:
        self.validate_configuration()
        return []

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
