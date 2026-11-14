import hashlib
import re
from urllib.parse import urlsplit, urlunsplit

from app.models.jobs import JobSource
from app.schemas.jobs import NormalizedJob

WORK_MODE = {
    "remote": "REMOTE", "work from home": "REMOTE", "work from anywhere": "REMOTE",
    "hybrid": "HYBRID", "hybrid work": "HYBRID", "onsite": "ONSITE", "on-site": "ONSITE",
    "office": "ONSITE", "in office": "ONSITE",
}
EMPLOYMENT_TYPE = {
    "full time": "FULL_TIME", "full-time": "FULL_TIME", "permanent": "FULL_TIME",
    "part time": "PART_TIME", "part-time": "PART_TIME", "contract": "CONTRACT",
    "contractor": "CONTRACT", "internship": "INTERNSHIP", "intern": "INTERNSHIP", "temporary": "TEMPORARY",
}


def normalized_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None


def comparison_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def normalize_url(value: str | None, base_url: str | None = None) -> str | None:
    if not value:
        return None
    from urllib.parse import urljoin
    value = urljoin(base_url or "", value.strip())
    parts = urlsplit(value)
    if parts.scheme.casefold() not in {"http", "https"} or not parts.hostname:
        return None
    host = parts.hostname.casefold()
    port = f":{parts.port}" if parts.port and not ((parts.scheme == "http" and parts.port == 80) or (parts.scheme == "https" and parts.port == 443)) else ""
    path = parts.path or "/"
    return urlunsplit((parts.scheme.casefold(), host + port, path, parts.query, ""))


def normalize_job(data: dict, source: JobSource) -> NormalizedJob:
    title = normalized_text(data.get("title")) or ""
    company = normalized_text(data.get("company_name")) or ""
    description = normalized_text(data.get("description")) or ""
    mode_raw = normalized_text(data.get("work_mode"))
    mode = WORK_MODE.get((mode_raw or "").casefold())
    if not mode and mode_raw:
        mode = mode_raw.upper().replace(" ", "_") if mode_raw.upper() in {"REMOTE", "HYBRID", "ONSITE"} else None
    employment_raw = normalized_text(data.get("employment_type"))
    employment = EMPLOYMENT_TYPE.get((employment_raw or "").casefold())
    if not employment and employment_raw:
        candidate = employment_raw.upper().replace(" ", "_").replace("-", "_")
        employment = candidate if candidate in set(EMPLOYMENT_TYPE.values()) else None

    currency_raw = normalized_text(data.get("salary_currency"))
    currency_map = {"₹": "INR", "RS": "INR", "RS.": "INR", "INR": "INR", "$": "USD", "USD": "USD", "€": "EUR", "EUR": "EUR", "GBP": "GBP", "£": "GBP"}
    currency = currency_map.get((currency_raw or "").upper())
    period_raw = normalized_text(data.get("salary_period"))
    period = period_raw.upper() if period_raw and period_raw.upper() in {"ANNUAL", "MONTHLY", "HOURLY"} else None
    salary_min = data.get("salary_min") if currency and period else None
    salary_max = data.get("salary_max") if currency and period else None
    raw = dict(data.get("raw_data") or {})
    raw.setdefault("source_values", {key: data.get(key) for key in ("title", "company_name", "location", "work_mode", "employment_type", "salary_min", "salary_max", "salary_currency", "salary_period") if data.get(key) is not None})
    content_hash = hashlib.sha256(comparison_key(description).encode("utf-8")).hexdigest() if description else None
    external_id = normalized_text(data.get("external_id"))
    job_url = normalize_url(data.get("job_url"), source.base_url)
    apply_url = normalize_url(data.get("apply_url"), source.base_url)
    if external_id is None:
        external_id = job_url or apply_url
    return NormalizedJob(
        external_id=external_id, source_id=source.id, source_name=source.name, title=title,
        company_name=company, description=description, employment_type=employment,
        experience_min=data.get("experience_min"), experience_max=data.get("experience_max"),
        location=normalized_text(data.get("location")), work_mode=mode,
        salary_min=salary_min, salary_max=salary_max, salary_currency=currency, salary_period=period,
        required_skills=list(dict.fromkeys(normalized_text(s) for s in (data.get("required_skills") or []) if normalized_text(s))),
        preferred_skills=list(dict.fromkeys(normalized_text(s) for s in (data.get("preferred_skills") or []) if normalized_text(s))),
        job_url=job_url, apply_url=apply_url, posted_at=data.get("posted_at"), expires_at=data.get("expires_at"),
        raw_data=raw, content_hash=content_hash,
    )
