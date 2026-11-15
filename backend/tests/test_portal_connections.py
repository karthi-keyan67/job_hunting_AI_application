from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.models.enums import JobSourceStatus, RunStatus
from app.models.integrations import GoogleOAuthConnection, IntegrationAuditLog
from app.models.jobs import CollectionRun, JobSource
from app.models.account import User
from app.services.google_oauth import GMAIL_READONLY_SCOPE


async def auth(client, email):
    response = await client.post("/api/v1/auth/register", json={"email": email, "password": "correct-horse-battery-1"})
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def alert_payload(**overrides):
    return {"allowed_senders": ["jobs@portal.example"], "required_terms": ["python"], "label_ids": ["INBOX"], **overrides}


@pytest.mark.asyncio
async def test_portal_connections_require_auth_and_report_real_capabilities(client):
    assert (await client.get("/api/v1/integrations/job-portals")).status_code == 401
    headers = await auth(client, "portal-overview@example.com")
    response = await client.get("/api/v1/integrations/job-portals", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert {item["platform"] for item in body["items"]} == {"LINKEDIN", "NAUKRI", "INDEED", "INSTAHYRE", "CUTSHORT", "HIRIST"}
    assert all(item["portal_account_connected"] is False for item in body["items"])
    assert all(item["connection_method"] == "GMAIL_JOB_ALERTS" for item in body["items"])


@pytest.mark.asyncio
async def test_unsupported_direct_portal_source_stays_disabled_and_bad_sender_is_rejected(client):
    headers = await auth(client, "portal-permissions@example.com")
    created = await client.post("/api/v1/sources", headers=headers, json={"name": "LinkedIn", "source_type": "LINKEDIN", "is_enabled": True})
    assert created.status_code == 201 and created.json()["is_enabled"] is False
    source_id = created.json()["id"]
    denied = await client.patch(f"/api/v1/sources/{source_id}", headers=headers, json={"is_enabled": True})
    assert denied.status_code == 409
    bad_sender = await client.put("/api/v1/integrations/job-portals/INDEED/alerts", headers=headers,
                                  json=alert_payload(allowed_senders=["not-an-email"]))
    assert bad_sender.status_code == 422


@pytest.mark.asyncio
async def test_alert_configuration_is_user_owned_and_disabled_until_gmail_is_connected(client, db_session):
    owner = await auth(client, "portal-owner@example.com")
    stranger = await auth(client, "portal-stranger@example.com")
    configured = await client.put("/api/v1/integrations/job-portals/NAUKRI/alerts", headers=owner, json=alert_payload())
    assert configured.status_code == 200
    assert configured.json()["alert_source_configured"] is True
    assert configured.json()["discovery_enabled"] is False
    assert configured.json()["portal_account_connected"] is False
    source_id = configured.json()["source_id"]
    source = await db_session.get(JobSource, source_id)
    assert source and source.user_id
    assert source.source_type == "GMAIL_ALERT" and source.status == JobSourceStatus.DISABLED
    assert source.configuration["allowed_senders"] == ["jobs@portal.example"]
    assert (await client.get(f"/api/v1/sources/{source_id}", headers=stranger)).status_code == 404
    other_overview = await client.get("/api/v1/integrations/job-portals", headers=stranger)
    naukri = next(item for item in other_overview.json()["items"] if item["platform"] == "NAUKRI")
    assert naukri["source_id"] is None
    enable_as_stranger = await client.patch("/api/v1/integrations/job-portals/NAUKRI/discovery", headers=stranger, json={"enabled": True})
    assert enable_as_stranger.status_code == 409
    enable_without_gmail = await client.patch("/api/v1/integrations/job-portals/NAUKRI/discovery", headers=owner, json={"enabled": True})
    assert enable_without_gmail.status_code == 409
    events = list(await db_session.scalars(select(IntegrationAuditLog).where(IntegrationAuditLog.user_id == source.user_id)))
    assert [event.action for event in events] == ["ALERT_SOURCE_CREATED"]


@pytest.mark.asyncio
async def test_connected_gmail_allows_discovery_and_history_is_scoped(client, db_session):
    owner = await auth(client, "portal-history-owner@example.com")
    other = await auth(client, "portal-history-other@example.com")
    user = await db_session.scalar(select(User).where(User.email == "portal-history-owner@example.com"))
    db_session.add(GoogleOAuthConnection(user_id=user.id, encrypted_credentials=Fernet.generate_key().decode(),
                                        scopes=[GMAIL_READONLY_SCOPE]))
    await db_session.commit()
    configured = await client.put("/api/v1/integrations/job-portals/LINKEDIN/alerts", headers=owner, json=alert_payload())
    source_id = configured.json()["source_id"]
    source = await db_session.get(JobSource, source_id)
    run = CollectionRun(source_id=source.id, status=RunStatus.FAILED, jobs_found=0, jobs_created=0,
                        jobs_updated=0, jobs_skipped=0, error_message="Gmail fetch failed", error_summary="Gmail fetch failed")
    db_session.add(run)
    await db_session.commit()
    enabled = await client.patch("/api/v1/integrations/job-portals/LINKEDIN/discovery", headers=owner, json={"enabled": True})
    assert enabled.status_code == 200 and enabled.json()["discovery_enabled"] is True
    assert enabled.json()["last_run"]["status"] == "FAILED"
    assert enabled.json()["last_run"]["error"] == "Gmail fetch failed"
    history = await client.get("/api/v1/integrations/job-portals/LINKEDIN/history", headers=owner)
    assert history.status_code == 200 and history.json()["items"][0]["id"] == str(run.id)
    events = await client.get("/api/v1/integrations/job-portals/audit?platform=LINKEDIN", headers=owner)
    assert [event["action"] for event in events.json()] == ["DISCOVERY_ENABLED", "ALERT_SOURCE_CREATED"]
    assert (await client.get("/api/v1/integrations/job-portals/LINKEDIN/history", headers=other)).json()["items"] == []
    assert (await client.get("/api/v1/integrations/job-portals/audit", headers=other)).json() == []


@pytest.mark.asyncio
async def test_disconnecting_gmail_disables_alert_sources_and_is_audited(client, db_session, monkeypatch):
    from types import SimpleNamespace
    from google.oauth2.credentials import Credentials

    encryption_key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.services.google_oauth.get_settings", lambda: SimpleNamespace(
        google_oauth_client_id="test-id", google_oauth_client_secret="test-secret",
        google_oauth_redirect_uri="https://example.test/callback", oauth_token_encryption_key=encryption_key))
    headers = await auth(client, "portal-disconnect@example.com")
    user = await db_session.scalar(select(User).where(User.email == "portal-disconnect@example.com"))
    configuration = {"platform": "HIRIST", "allowed_senders": ["jobs@hirist.example"], "required_terms": [], "label_ids": []}
    source = JobSource(user_id=user.id, name="Hirist alerts", source_type="GMAIL_ALERT", connector_type="GMAIL_ALERT",
                       configuration=configuration, is_enabled=True, status=JobSourceStatus.ENABLED)
    credentials = Credentials(token="access", refresh_token="refresh", token_uri="https://oauth2.googleapis.com/token",
                              client_id="id", client_secret="secret", scopes=[GMAIL_READONLY_SCOPE],
                              expiry=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1))
    from app.services.google_oauth import GoogleOAuthService
    service = GoogleOAuthService(db_session)
    encrypted = service._fernet().encrypt(credentials.to_json().encode()).decode()
    db_session.add_all([source, GoogleOAuthConnection(user_id=user.id, encrypted_credentials=encrypted, scopes=[GMAIL_READONLY_SCOPE])])
    await db_session.commit()

    class FakeResponse:
        status_code = 200

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return None
        async def post(self, *_args, **_kwargs): return FakeResponse()

    monkeypatch.setattr("app.services.google_oauth.httpx.AsyncClient", lambda **_kwargs: FakeClient())
    response = await client.delete("/api/v1/integrations/gmail/connection", headers=headers)
    assert response.status_code == 204, response.text
    await db_session.refresh(source)
    assert source.is_enabled is False
    events = list(await db_session.scalars(select(IntegrationAuditLog).where(IntegrationAuditLog.user_id == user.id).order_by(IntegrationAuditLog.occurred_at)))
    assert {event.action for event in events} == {"DISCOVERY_DISABLED", "ACCOUNT_DISCONNECTED"}
