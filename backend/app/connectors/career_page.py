import asyncio
import time
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from app.connectors.base import ConnectorError, JobConnector
from app.connectors.security import ensure_public_dns, validate_public_url


class CareerPageConnector(JobConnector):
    """Configurable public HTML career page parser; no login, browser automation, or evasion."""

    user_agent = "AIJobHuntingAgent/1.0 (+public career page collector; contact site owner)"

    def __init__(self, source, *, transport: httpx.AsyncBaseTransport | None = None):
        super().__init__(source)
        self.transport = transport

    def validate_configuration(self) -> None:
        config = self.source.configuration or {}
        selectors = config.get("selectors") or {}
        if not self.source.base_url:
            raise ConnectorError("A career page URL is required")
        validate_public_url(self.source.base_url)
        if not selectors.get("job_card") or not selectors.get("title") or not selectors.get("company"):
            raise ConnectorError("Configure job_card, title, and company CSS selectors")
        interval = config.get("request_interval_seconds", 1)
        if not isinstance(interval, (int, float)) or interval < 0 or interval > 60:
            raise ConnectorError("Request interval must be between 0 and 60 seconds")

    async def fetch_jobs(self) -> list[dict]:
        self.validate_configuration()
        config = self.source.configuration
        selectors = config["selectors"]
        max_pages = max(1, min(int(config.get("max_pages", 1)), 10))
        next_selector = (config.get("pagination") or {}).get("next_link")
        timeout = httpx.Timeout(15.0, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False,
                                     headers={"User-Agent": self.user_agent}, transport=self.transport) as client:
            current = self.source.base_url
            await ensure_public_dns(current)
            robots = await self._robots(client, current)
            jobs: list[dict] = []
            last_request = time.monotonic()
            seen_pages: set[str] = set()
            for _ in range(max_pages):
                current = validate_public_url(current)
                if current in seen_pages or not robots.can_fetch(self.user_agent, current):
                    break
                seen_pages.add(current)
                last_request = await self._wait_interval(last_request, config.get("request_interval_seconds", 1))
                response = await self._get(client, current)
                soup = BeautifulSoup(response.text, "html.parser")
                jobs.extend(self._extract(soup, current, selectors, config))
                next_anchor = soup.select_one(next_selector) if next_selector else None
                href = next_anchor.get("href") if next_anchor else None
                if not href:
                    break
                current = urljoin(current, href)
                await ensure_public_dns(current)
            return jobs

    async def _robots(self, client: httpx.AsyncClient, page_url: str) -> RobotFileParser:
        parts = urlsplit(page_url)
        robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
        await ensure_public_dns(robots_url)
        response = await self._get(client, robots_url, allow_not_found=True)
        parser = RobotFileParser(robots_url)
        if response is None:
            parser.parse([])
        else:
            parser.parse(response.text.splitlines())
        return parser

    async def _get(self, client: httpx.AsyncClient, url: str, *, allow_not_found: bool = False):
        for attempt in range(3):
            try:
                response = await client.get(url)
                if allow_not_found and response.status_code == 404:
                    return None
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < 2:
                        await asyncio.sleep(min(0.25 * (2 ** attempt), 1.0))
                        continue
                if response.is_redirect:
                    raise ConnectorError("Redirects are not followed; configure the final public URL")
                if response.status_code in {401, 403}:
                    raise ConnectorError("The page denies public access")
                response.raise_for_status()
                return response
            except ConnectorError:
                raise
            except httpx.HTTPStatusError as exc:
                if allow_not_found and exc.response.status_code == 404:
                    return None
                raise ConnectorError(f"Career page returned HTTP {exc.response.status_code}") from exc
            except httpx.HTTPError as exc:
                if attempt < 2:
                    await asyncio.sleep(min(0.25 * (2 ** attempt), 1.0))
                    continue
                raise ConnectorError("Career page request failed") from exc
        raise ConnectorError("Career page is temporarily unavailable")

    async def _wait_interval(self, previous: float, seconds: float) -> float:
        now = time.monotonic()
        delay = seconds - (now - previous) if previous else 0
        if delay > 0:
            await asyncio.sleep(delay)
        return time.monotonic()

    @staticmethod
    def _text(card, selector: str | None) -> str | None:
        if not selector:
            return None
        element = card.select_one(selector)
        return element.get_text(" ", strip=True) if element else None

    def _extract(self, soup: BeautifulSoup, page_url: str, selectors: dict, config: dict) -> list[dict]:
        output = []
        for card in soup.select(selectors["job_card"]):
            title = self._text(card, selectors["title"])
            company = self._text(card, selectors["company"])
            if not title or not company:
                continue
            link = card.select_one(selectors.get("job_url", "a[href]"))
            href = link.get("href") if link else None
            job_url = urljoin(page_url, href) if href else None
            external = card.get(config.get("id_attribute", "data-job-id"))
            if not external:
                external = job_url
            description = self._text(card, selectors.get("description")) or ""
            location = self._text(card, selectors.get("location"))
            work_mode = self._text(card, selectors.get("work_mode"))
            salary_text = self._text(card, selectors.get("salary"))
            salary_currency = config.get("salary_currency") if salary_text else None
            salary_period = config.get("salary_period") if salary_text else None
            # Do not interpret compensation until both its currency and period are declared.
            salary_min = salary_max = None
            if salary_text and salary_currency and salary_period:
                import re
                amounts = [float(value.replace(",", "")) for value in re.findall(r"\d[\d,]*(?:\.\d+)?", salary_text)]
                salary_unit = str(config.get("salary_unit", "")).upper()
                if re.search(r"\bLPA\b|\bLAKHS?\b", salary_text, re.I):
                    salary_unit = "LAKH"
                if re.search(r"\bCRORES?\b|\bCR\b", salary_text, re.I):
                    salary_unit = "CRORE"
                multiplier = {"BASE": 1, "THOUSAND": 1000, "LAKH": 100_000, "CRORE": 10_000_000}.get(salary_unit)
                amounts = [amount * multiplier for amount in amounts] if multiplier else []
                salary_min = amounts[0] if amounts else None
                salary_max = amounts[-1] if len(amounts) > 1 else salary_min
            skills = []
            if selectors.get("required_skills"):
                for skill in card.select(selectors["required_skills"]):
                    value = skill.get_text(" ", strip=True)
                    if value:
                        skills.append(value)
            experience = self._text(card, selectors.get("experience"))
            experience_min = experience_max = None
            if experience:
                import re
                range_match = re.search(r"(\d+)\s*(?:-|to)\s*(\d+)\s*(years?|months?)", experience, re.I)
                single_match = re.search(r"(\d+)\s*(years?|months?)", experience, re.I)
                match = range_match or single_match
                if match:
                    factor = 12 if match.group(match.lastindex).casefold().startswith("year") else 1
                    experience_min = int(match.group(1)) * factor
                    experience_max = int(match.group(2)) * factor if range_match else experience_min
            output.append({
                "external_id": external, "title": title, "company_name": company,
                "description": description, "location": location, "work_mode": work_mode,
                "employment_type": self._text(card, selectors.get("employment_type")),
                "salary_min": salary_min, "salary_max": salary_max,
                "salary_currency": salary_currency, "salary_period": salary_period,
                "experience_min": experience_min, "experience_max": experience_max,
                "required_skills": skills, "job_url": job_url, "apply_url": job_url,
                "raw_data": {"page_url": page_url, "salary_text": salary_text, "source_values": {"title": title, "company": company, "location": location}},
            })
        return output
