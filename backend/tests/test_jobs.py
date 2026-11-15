from pathlib import Path
import uuid

import pytest
from sqlalchemy import select

from app.connectors.career_page import CareerPageConnector
from app.connectors.gmail_alerts import GmailJobAlertConnector
from app.connectors.security import validate_public_url
from app.models.enums import JobSourceStatus, RunStatus
from app.models.jobs import CollectionRun, Job, JobDuplicate, JobSource
from app.services.job_normalization import normalize_job
from app.services.jobs import JobService

FIXTURES = Path(__file__).parent / "fixtures"


def source(source_type="CAREER_PAGE", **kwargs):
    values = {"id": uuid.uuid4(), "name": "Fixture Careers", "source_type": source_type,
              "connector_type": source_type, "configuration": {}, "base_url": "https://careers.example.org"}
    values.update(kwargs)
    return JobSource(**values)


def test_public_career_parser_fixture_handles_missing_fields_and_configured_salary():
    page_source = source(configuration={
        "selectors": {"job_card": ".opening", "title": ".role", "company": ".employer", "description": ".description",
                      "location": ".city", "work_mode": ".mode", "job_url": "a.apply", "required_skills": ".skill",
                      "salary": ".salary", "experience": ".experience"},
        "salary_currency": "INR", "salary_period": "ANNUAL", "salary_unit": "BASE",
    })
    connector = CareerPageConnector(page_source)
    jobs = connector._extract(__import__("bs4").BeautifulSoup((FIXTURES / "career_page.html").read_text(), "html.parser"),
                              "https://careers.example.org/openings", page_source.configuration["selectors"], page_source.configuration)
    assert len(jobs) == 1
    normalized = connector.normalize_job(jobs[0])
    assert normalized.work_mode == "HYBRID"
    assert normalized.experience_min == 24 and normalized.experience_max == 36
    assert normalized.salary_min == 1_200_000 and normalized.salary_period == "ANNUAL"
    assert normalized.required_skills == ["Python", "FastAPI"]
    assert normalized.apply_url == "https://careers.example.org/careers/role-104"


def test_public_career_parser_uses_configured_company_when_selector_is_missing():
    from bs4 import BeautifulSoup

    configuration = {
        "company_name": " Citi ",
        "selectors": {
            "job_card": ".sr-job-item", "title": ".sr-job-item__title", "location": ".sr-job-location",
            "work_mode": ".sr-job-type", "job_url": "a.sr-job-item__link",
        },
    }
    page_source = source(configuration=configuration)
    connector = CareerPageConnector(page_source)
    connector.validate_configuration()
    html = """<ul><li class='sr-job-item'><h3 class='sr-job-item__title'>Python Engineer</h3>
    <span class='sr-job-location'>Chennai, Tamil Nadu, India</span><span class='sr-job-type'>Hybrid</span>
    <a class='sr-job-item__link' href='/job/python-engineer/123'>View job</a></li></ul>"""
    jobs = connector._extract(BeautifulSoup(html, "html.parser"), page_source.base_url, configuration["selectors"], configuration)

    assert len(jobs) == 1
    assert jobs[0]["company_name"] == "Citi"
    assert jobs[0]["description"] == ""
    assert jobs[0]["location"] == "Chennai, Tamil Nadu, India"
    assert jobs[0]["work_mode"] == "Hybrid"
    assert jobs[0]["job_url"] == "https://careers.example.org/job/python-engineer/123"


def test_public_career_parser_requires_company_selector_or_nonempty_fallback():
    from app.connectors.base import ConnectorError

    selectors = {"job_card": ".opening", "title": ".role"}
    with pytest.raises(ConnectorError, match="company selector or non-empty company_name"):
        CareerPageConnector(source(configuration={"selectors": selectors})).validate_configuration()
    with pytest.raises(ConnectorError, match="company selector or non-empty company_name"):
        CareerPageConnector(source(configuration={"company_name": "  ", "selectors": selectors})).validate_configuration()
    # Selector-based configurations remain valid without introducing the fallback key.
    CareerPageConnector(source(configuration={"selectors": {**selectors, "company": ".employer"}})).validate_configuration()


@pytest.mark.asyncio
async def test_public_career_connector_fetches_static_cards_with_company_fallback(monkeypatch):
    import asyncio
    import httpx
    import app.connectors.career_page as career_module

    monkeypatch.setattr(career_module, "ensure_public_dns", lambda _url: asyncio.sleep(0))
    requested = []
    html = """<ul><li class='sr-job-item'><h3 class='sr-job-item__title'>Python Engineer</h3>
    <span class='sr-job-location'>Chennai, Tamil Nadu, India</span><span class='sr-job-type'>Hybrid</span>
    <a class='sr-job-item__link' href='/job/python-engineer/123'>View job</a></li></ul>"""

    async def handler(request):
        requested.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(200, text=html)

    configuration = {
        "company_name": "Citi", "request_interval_seconds": 0,
        "selectors": {"job_card": ".sr-job-item", "title": ".sr-job-item__title", "location": ".sr-job-location",
                      "work_mode": ".sr-job-type", "job_url": "a.sr-job-item__link"},
    }
    page_source = source(configuration=configuration, base_url="https://careers.example.org/location/chennai")
    jobs = await CareerPageConnector(page_source, transport=httpx.MockTransport(handler)).fetch_jobs()

    assert requested == ["/robots.txt", "/location/chennai"]
    assert len(jobs) == 1
    assert jobs[0]["company_name"] == "Citi"
    assert jobs[0]["description"] == ""
    assert jobs[0]["external_id"] == "https://careers.example.org/job/python-engineer/123"
    normalized = CareerPageConnector(page_source).normalize_job(jobs[0])
    assert normalized.company_name == "Citi" and normalized.description == ""


@pytest.mark.asyncio
async def test_public_career_connector_respects_robots_and_extracts_fixture(monkeypatch):
    import httpx
    import app.connectors.career_page as career_module
    monkeypatch.setattr(career_module, "ensure_public_dns", lambda _url: __import__("asyncio").sleep(0))
    html = (FIXTURES / "career_page.html").read_text()
    requested = []
    async def handler(request):
        requested.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(200, text=html)
    page_source = source(configuration={"request_interval_seconds": 0,
        "selectors": {"job_card": ".opening", "title": ".role", "company": ".employer", "job_url": "a.apply"}},
        base_url="https://careers.example.org/openings")
    result = await CareerPageConnector(page_source, transport=httpx.MockTransport(handler)).fetch_jobs()
    assert requested == ["/robots.txt", "/openings"]
    assert len(result) == 1 and result[0]["external_id"] == "role-104"


@pytest.mark.asyncio
async def test_public_career_connector_does_not_fetch_disallowed_or_redirected_pages(monkeypatch):
    import httpx
    import app.connectors.career_page as career_module
    monkeypatch.setattr(career_module, "ensure_public_dns", lambda _url: __import__("asyncio").sleep(0))
    requested = []
    async def robots_block(request):
        requested.append(request.url.path)
        return httpx.Response(200, text="User-agent: *\nDisallow: /")
    config = {"request_interval_seconds": 0, "selectors": {"job_card": "article", "title": "h2", "company": ".company"}}
    await CareerPageConnector(source(configuration=config), transport=httpx.MockTransport(robots_block)).fetch_jobs()
    assert requested == ["/robots.txt"]

    async def redirect(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})
    with pytest.raises(Exception, match="Redirects are not followed"):
        await CareerPageConnector(source(configuration=config), transport=httpx.MockTransport(redirect)).fetch_jobs()


@pytest.mark.asyncio
async def test_public_career_connector_retries_transient_server_failures_three_times():
    import httpx
    connector = CareerPageConnector(source())
    attempts = 0
    async def handler(_request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(503 if attempts < 3 else 200, text="ready")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await connector._get(client, "https://careers.example.org/jobs")
    assert response.text == "ready" and attempts == 3


def test_unknown_compensation_and_experience_are_not_invented():
    item = normalize_job({"title": "Backend Engineer", "company_name": "Example", "salary_min": 0,
                          "experience_min": None, "work_mode": None}, source())
    assert item.salary_min is None and item.salary_max is None and item.salary_currency is None
    assert item.experience_min is None and item.work_mode is None


def test_work_mode_and_currency_normalization():
    item = normalize_job({"title": "Role", "company_name": "Co", "work_mode": "Work from home",
                          "salary_min": 5000, "salary_max": 7000, "salary_currency": "₹", "salary_period": "MONTHLY"}, source())
    assert item.work_mode == "REMOTE"
    assert item.salary_currency == "INR" and item.salary_period == "MONTHLY"
    assert item.salary_min == 5000


def test_manual_url_ssrf_and_scheme_validation():
    for url in ("http://127.0.0.1/path", "https://localhost/", "http://10.1.2.3", "file:///etc/passwd", "https://user:pw@example.com"):
        with pytest.raises(Exception):
            validate_public_url(url)
    assert validate_public_url("https://8.8.8.8/jobs") == "https://8.8.8.8/jobs"


def test_gmail_job_alert_fixture_parser_filters_sender_and_preserves_message_id():
    raw = (FIXTURES / "job_alert.eml").read_bytes()
    parsed = GmailJobAlertConnector.parse_message(raw, ["careers@example.org"], ["engineer"])
    assert len(parsed) == 1
    assert parsed[0]["external_id"] == "<job-77@example.org>"
    assert parsed[0]["company_name"] == "Example AI"
    assert parsed[0]["location"] == "Chennai"
    assert GmailJobAlertConnector.parse_message(raw, ["other@example.org"]) == []


def test_gmail_alert_adapter_never_fabricates_company_and_portal_formats_wait_for_samples():
    from email.message import EmailMessage

    message = EmailMessage()
    message["From"] = "alerts@example.org"
    message["Subject"] = "Python Engineer opening"
    message.set_content("Build APIs. View job: https://jobs.example.org/1")
    raw = message.as_bytes()
    assert GmailJobAlertConnector.parse_message(raw, ["alerts@example.org"]) == []
    for platform in ("LINKEDIN", "NAUKRI", "INDEED", "INSTAHYRE", "CUTSHORT", "HIRIST"):
        parsed, _body, _sender, _subject, reason = GmailJobAlertConnector._extract(
            raw, ["alerts@example.org"], [], platform
        )
        assert parsed == []
        assert reason == f"{platform} alert parser awaiting sanitized sample"


def test_gmail_generic_alert_accepts_explicit_title_and_company_fields():
    from email.message import EmailMessage

    message = EmailMessage()
    message["From"] = "alerts@example.org"
    message["Subject"] = "New opening"
    message.set_content("Title: Python Engineer Company: Example Inc Location: Chennai View job: https://jobs.example.org/1")
    parsed = GmailJobAlertConnector.parse_message(message.as_bytes(), ["alerts@example.org"])
    assert len(parsed) == 1
    assert parsed[0]["title"] == "Python Engineer"
    assert parsed[0]["company_name"] == "Example Inc"


@pytest.mark.asyncio
async def test_gmail_mock_transport_queues_unknown_message_and_advances_incremental_cursor(monkeypatch):
    import base64
    from email.message import EmailMessage
    from types import SimpleNamespace
    import app.connectors.gmail_alerts as gmail_module
    from app.services.google_oauth import GoogleOAuthService

    user_id = uuid.uuid4()
    page_source = source("GMAIL_ALERT", user_id=user_id, configuration={"allowed_senders": ["alerts@example.org"]})
    message = EmailMessage()
    message["From"] = "alerts@example.org"
    message["Subject"] = "Python Engineer opening"
    message.set_content("A new role. https://jobs.example.org/1")
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")

    class FakeSession:
        def __init__(self): self.added, self.lookups = [], 0
        async def scalar(self, _query):
            self.lookups += 1
            return None if self.lookups == 1 else SimpleNamespace(status="NEEDS_REVIEW", sender="alerts@example.org", subject="Python Engineer opening")
        async def scalars(self, _query): return SimpleNamespace(all=lambda: [])
        def add(self, row): self.added.append(row)

    class FakeResponse:
        def __init__(self, payload): self.status_code, self.payload = 200, payload
        def json(self): return self.payload

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return None
        async def get(self, url, *, headers, params):
            if url.endswith("/messages"):
                return FakeResponse({"messages": [{"id": "gmail-message-1"}]})
            return FakeResponse({"raw": raw, "internalDate": "1794700000000"})

    monkeypatch.setattr(gmail_module, "httpx", SimpleNamespace(AsyncClient=lambda **_kwargs: FakeClient()))
    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(
        google_oauth_client_id="client", google_oauth_client_secret="secret",
        google_oauth_redirect_uri="https://app.example.test/callback", oauth_token_encryption_key="key"))
    async def access_token(self, _user_id): return "mock-token"
    monkeypatch.setattr(GoogleOAuthService, "access_token", access_token)
    session = FakeSession()

    result = await GmailJobAlertConnector(page_source, session).fetch_jobs()

    assert result == []
    assert len(session.added) == 1
    assert session.added[0].gmail_message_id == "gmail-message-1"
    assert session.added[0].status == "NEEDS_REVIEW"
    assert page_source.configuration["last_synced_internal_date_ms"] == 1794700000000
    assert await GmailJobAlertConnector(page_source, session).fetch_jobs() == []
    assert len(session.added) == 1


@pytest.mark.asyncio
async def test_manual_import_url_validation_and_user_ownership(client):
    signup = await client.post("/api/v1/auth/register", json={"email": "job-import@example.com", "password": "correct-horse-battery-1"})
    headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}
    bad = await client.post("/api/v1/jobs/import", headers=headers, json={"title": "Engineer", "company_name": "Co", "apply_url": "http://127.0.0.1/apply"})
    assert bad.status_code == 422
    imported = await client.post("/api/v1/jobs/import", headers=headers, json={
        "title": "Python Backend Developer", "company_name": "Example Co", "location": "Chennai",
        "description": "Build APIs", "job_url": "https://8.8.8.8/jobs/1", "apply_url": "https://8.8.8.8/jobs/1/apply",
    })
    assert imported.status_code == 201, imported.text
    row = imported.json()
    assert row["source_name"] == "Manual imports" and row["possible_duplicate"] is False
    assert row["salary_min"] is None and row["experience_min"] is None
    jobs = await client.get("/api/v1/jobs?search=Python&location=Chennai", headers=headers)
    assert jobs.status_code == 200 and jobs.json()["total"] == 1
    stranger = await client.post("/api/v1/auth/register", json={"email": "job-stranger@example.com", "password": "correct-horse-battery-1"})
    stranger_headers = {"Authorization": f"Bearer {stranger.json()['access_token']}"}
    assert (await client.get(f"/api/v1/jobs/{row['id']}", headers=stranger_headers)).status_code == 404
    assert (await client.get("/api/v1/jobs", headers=stranger_headers)).json()["total"] == 0


@pytest.mark.asyncio
async def test_sources_crud_ownership_and_portal_status(client):
    signup = await client.post("/api/v1/auth/register", json={"email": "source-owner@example.com", "password": "correct-horse-battery-1"})
    headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}
    created = await client.post("/api/v1/sources", headers=headers, json={"name": "LinkedIn", "source_type": "LINKEDIN", "is_enabled": False})
    assert created.status_code == 201, created.text
    source_id = created.json()["id"]
    assert created.json()["integration_status"] == "AWAITING_AUTHORIZED_API_OR_FEED"
    check = await client.post(f"/api/v1/sources/{source_id}/test", headers=headers)
    assert check.status_code == 200 and check.json()["status"] == "not_configured"
    disabled = await client.patch(f"/api/v1/sources/{source_id}", headers=headers, json={"name": "LinkedIn (disabled)"})
    assert disabled.status_code == 200
    assert (await client.get(f"/api/v1/sources/{source_id}")).status_code == 401
    deleted = await client.delete(f"/api/v1/sources/{source_id}", headers=headers)
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_probable_cross_source_duplicate_preserves_both_jobs(db_session):
    from app.models.account import User
    user = User(email="dedupe@example.com", password_hash="not-a-real-user-password-hash")
    db_session.add(user)
    await db_session.flush()
    first_source = JobSource(user_id=user.id, name="Source A", source_type="CAREER_PAGE", connector_type="CAREER_PAGE", is_enabled=True, configuration={})
    second_source = JobSource(user_id=user.id, name="Source B", source_type="CAREER_PAGE", connector_type="CAREER_PAGE", is_enabled=True, configuration={})
    db_session.add_all([first_source, second_source])
    await db_session.flush()
    service = JobService(db_session)
    first, _, created = await service._store(normalize_job({"external_id": "a-1", "title": "Python Backend Developer", "company_name": "Example Co", "location": "Chennai", "description": "Build APIs", "apply_url": "https://8.8.8.8/apply"}, first_source), user.id, first_source)
    second, possible, created_second = await service._store(normalize_job({"external_id": "b-1", "title": "python backend developer", "company_name": "example co", "location": "Chennai", "description": "Build APIs", "apply_url": "https://8.8.8.8/apply"}, second_source), user.id, second_source)
    await db_session.commit()
    links = list((await db_session.scalars(select(JobDuplicate))).all())
    assert created and created_second and possible
    assert first.id != second.id and len(links) == 1


@pytest.mark.asyncio
async def test_partial_unique_collection_index_locks_source(db_session):
    from app.models.account import User
    from sqlalchemy.exc import IntegrityError
    user = User(email="lock-owner@example.com", password_hash="not-a-real-user-password-hash")
    db_session.add(user)
    await db_session.flush()
    source_row = JobSource(user_id=user.id, name="Lock test", source_type="GMAIL_ALERT", connector_type="GMAIL_ALERT", is_enabled=True,
                           status=JobSourceStatus.ENABLED, configuration={})
    db_session.add(source_row)
    await db_session.flush()
    db_session.add(CollectionRun(source_id=source_row.id, status=RunStatus.RUNNING))
    await db_session.commit()
    with pytest.raises(IntegrityError):
        db_session.add(CollectionRun(source_id=source_row.id, status=RunStatus.RUNNING))
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_collection_worker_upserts_idempotently_and_records_counts(db_session, monkeypatch):
    from app.models.account import User
    class FixtureConnector:
        def __init__(self, source_obj):
            self.source = source_obj
            self.items = [{"external_id": "role-1", "title": "Python Engineer", "company_name": "Example Co", "description": "Build services"}]
        def validate_configuration(self):
            return None
        async def fetch_jobs(self):
            return self.items
        def normalize_job(self, data):
            return normalize_job(data, self.source)
    user = User(email="collector@example.com", password_hash="not-a-real-user-password-hash")
    db_session.add(user)
    await db_session.flush()
    source_row = JobSource(user_id=user.id, name="Fixture", source_type="CAREER_PAGE", connector_type="CAREER_PAGE", is_enabled=True,
                           status=JobSourceStatus.ENABLED, base_url="https://careers.example.org", configuration={})
    db_session.add(source_row)
    await db_session.commit()
    connector = FixtureConnector(source_row)
    monkeypatch.setattr("app.services.jobs.connector_for", lambda _source, *_args: connector)
    service = JobService(db_session)
    first = await service.collect_source(source_row.id, user.id)
    assert first.status == RunStatus.SUCCEEDED and first.jobs_created == 1 and first.jobs_found == 1
    connector.items = [{"external_id": "role-1", "title": "Python Platform Engineer", "company_name": "Example Co", "description": "Updated listing"}]
    second = await service.collect_source(source_row.id, user.id)
    assert second.status == RunStatus.SUCCEEDED and second.jobs_updated == 1
    assert await db_session.scalar(select(Job).where(Job.source_id == source_row.id)) is not None
    assert await db_session.scalar(select(Job.id).where(Job.source_id == source_row.id).limit(1)) is not None


@pytest.mark.asyncio
async def test_collection_failure_is_recorded_without_throwing(client, monkeypatch):
    from app.connectors.base import ConnectorError
    class FailedConnector:
        def __init__(self, source_obj):
            self.source = source_obj
        def validate_configuration(self):
            return None
        async def fetch_jobs(self):
            raise ConnectorError("Authorized fixture connector failed")
        @staticmethod
        def handle_errors(_exc):
            return "Authorized fixture connector failed"
    monkeypatch.setattr("app.services.jobs.connector_for", lambda value, *_args: FailedConnector(value))
    signup = await client.post("/api/v1/auth/register", json={"email": "collector-fail@example.com", "password": "correct-horse-battery-1"})
    headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}
    response = await client.post("/api/v1/sources", headers=headers, json={"name": "Gmail alerts", "source_type": "GMAIL_ALERT", "configuration": {"allowed_senders": ["careers@example.org"]}, "is_enabled": True})
    source_id = response.json()["id"]
    run = await client.post(f"/api/v1/sources/{source_id}/collect", headers=headers)
    assert run.status_code == 200, run.text
    assert run.json()["status"] == "FAILED"
    assert "awaiting" not in (run.json()["error_message"] or "").lower()  # safe connector errors do not expose credentials


@pytest.mark.asyncio
async def test_gmail_source_requires_and_normalizes_sender_allowlist(client):
    signup = await client.post("/api/v1/auth/register", json={"email": "gmail-source@example.com", "password": "correct-horse-battery-1"})
    headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}
    invalid = await client.post("/api/v1/sources", headers=headers, json={"name": "Gmail", "source_type": "GMAIL_ALERT"})
    assert invalid.status_code == 422
    created = await client.post("/api/v1/sources", headers=headers, json={
        "name": "Gmail", "source_type": "GMAIL_ALERT", "configuration": {"allowed_senders": ["Careers@Example.org"]},
    })
    assert created.status_code == 201
    assert created.json()["configuration"]["allowed_senders"] == ["careers@example.org"]
