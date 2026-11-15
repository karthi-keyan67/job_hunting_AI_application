"""Conservative, format-specific parsers for email job alerts."""
from abc import ABC, abstractmethod
import re
from typing import Any


class AlertAdapter(ABC):
    platform: str

    @abstractmethod
    def parse(self, message: Any, body_text: str, links: list[str], sender: str) -> tuple[list[dict], str]:
        """Return normalized source fields and a review reason when extraction is uncertain."""


class GenericLabeledAlertAdapter(AlertAdapter):
    """Parser for explicit `Title:` and `Company:` alerts with an original job URL."""
    platform = "GENERIC"

    def parse(self, message: Any, body_text: str, links: list[str], sender: str) -> tuple[list[dict], str]:
        subject = str(message.get("Subject", ""))
        title_match = re.search(r"(?:job\s+)?title\s*:\s*(.{2,300}?)(?=\s+(?:company|location|description|view\s+job)\s*:|$)", body_text, re.I)
        company_match = re.search(r"company\s*:\s*(.{2,300}?)(?=\s+(?:title|location|description|view\s+job)\s*:|$)", body_text, re.I)
        location_match = re.search(r"location\s*:\s*(.{2,300}?)(?=\s+(?:title|company|description)\s*:|\s+view\s+job\b|$)", body_text, re.I)
        link = next((url for url in links if url.startswith(("https://", "http://"))), None)
        if not link:
            match = re.search(r"https?://[^\s<>\"']+", body_text)
            link = match.group(0).rstrip(".,)") if match else None
        title = title_match.group(1).strip() if title_match else subject.strip()
        if title.casefold() in {"job alert", "job alerts", "job opportunities", "new jobs"}:
            title = ""
        if not title or not company_match or not link:
            return [], "Required title, company, or job URL could not be reliably extracted"
        return ([{"external_id": message.get("Message-ID") or link, "title": title[:300],
                  "company_name": company_match.group(1).strip()[:300],
                  "location": location_match.group(1).strip()[:300] if location_match else None,
                  "description": body_text[:100_000], "job_url": link, "apply_url": link,
                  "raw_data": {"sender": sender, "alert_platform": self.platform}}], "")


class AwaitingSampleAlertAdapter(AlertAdapter):
    def __init__(self, platform: str):
        self.platform = platform

    def parse(self, message: Any, body_text: str, links: list[str], sender: str) -> tuple[list[dict], str]:
        del message, body_text, links, sender
        return [], f"{self.platform} alert parser awaiting sanitized sample"


class AlertAdapterRegistry:
    PLATFORMS = ("LINKEDIN", "NAUKRI", "INDEED", "INSTAHYRE", "CUTSHORT", "HIRIST")

    @classmethod
    def get(cls, platform: str) -> AlertAdapter:
        normalized = platform.upper()
        if normalized == "GENERIC":
            return GenericLabeledAlertAdapter()
        if normalized in cls.PLATFORMS:
            return AwaitingSampleAlertAdapter(normalized)
        raise ValueError("Unsupported alert platform")
