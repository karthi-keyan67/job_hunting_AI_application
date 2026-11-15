import base64
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.fernet import Fernet
from google.oauth2.credentials import Credentials
from sqlalchemy import select

from app.connectors.base import ConnectorNotConfigured
from app.models import GmailAlertReview, GoogleOAuthConnection, GoogleOAuthState, JobSource, JobSourceStatus, User
from app.services.google_oauth import GMAIL_READONLY_SCOPE, GoogleOAuthService


def _settings(key: str):
    return SimpleNamespace(
        google_oauth_client_id="test-client-id",
        google_oauth_client_secret="test-client-secret",
        google_oauth_redirect_uri="https://app.example.test/api/v1/integrations/gmail/callback",
        oauth_token_encryption_key=key,
    )


async def _authenticated_client(client, email="gmail-oauth@example.com"):
    result = await client.post("/api/v1/auth/register", json={"email": email, "password": "correct-horse-battery-1"})
    assert result.status_code == 201
    return {"Authorization": f"Bearer {result.json()['access_token']}"}


def _credentials(*, expired=False):
    expiry = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1) if expired else datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)
    return Credentials(
        token="test-access-token",
        refresh_token="test-refresh-token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="test-client-id",
        client_secret="test-client-secret",
        scopes=[GMAIL_READONLY_SCOPE],
        expiry=expiry,
    )


@pytest.mark.asyncio
async def test_gmail_oauth_authorization_encrypts_tokens_and_rejects_replay(client, db_session, monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr("app.services.google_oauth.get_settings", lambda: _settings(key))
    captured = {}

    class FakeFlow:
        def __init__(self, state):
            self.state = state
            self.credentials = _credentials()
            captured["scope"] = [GMAIL_READONLY_SCOPE]

        def authorization_url(self, **options):
            captured["options"] = options
            return f"https://accounts.google.com/o/oauth2/auth?state={self.state}", None

        def fetch_token(self, *, code):
            assert code == "test-code"

    monkeypatch.setattr(
        "app.services.google_oauth.Flow.from_client_config",
        staticmethod(lambda _config, scopes, state: FakeFlow(state) if scopes == [GMAIL_READONLY_SCOPE] else pytest.fail("Unexpected OAuth scope")),
    )
    headers = await _authenticated_client(client)
    authorization = await client.post("/api/v1/integrations/gmail/authorize", headers=headers)
    assert authorization.status_code == 200
    assert captured["options"]["access_type"] == "offline"
    assert captured["options"]["prompt"] == "consent"
    oauth_state = parse_qs(urlsplit(authorization.json()["authorization_url"]).query)["state"][0]
    stored_state = await db_session.scalar(select(GoogleOAuthState))
    assert stored_state is not None
    assert stored_state.state_hash != oauth_state and len(stored_state.state_hash) == 64

    callback = await client.get("/api/v1/integrations/gmail/callback", params={"state": oauth_state, "code": "test-code"})
    assert callback.status_code == 200 and callback.json()["connected"] is True
    connection = await db_session.scalar(select(GoogleOAuthConnection))
    assert connection is not None
    assert "test-access-token" not in connection.encrypted_credentials
    assert "test-refresh-token" not in connection.encrypted_credentials
    assert connection.scopes == [GMAIL_READONLY_SCOPE]
    assert (await client.get("/api/v1/integrations/gmail/status", headers=headers)).json()["connected"] is True

    replay = await client.get("/api/v1/integrations/gmail/callback", params={"state": oauth_state, "code": "test-code"})
    assert replay.status_code == 400


@pytest.mark.asyncio
async def test_gmail_oauth_refreshes_expired_access_token_with_stored_refresh_token(db_session, monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr("app.services.google_oauth.get_settings", lambda: _settings(key))
    user = User(email="gmail-refresh@example.com", password_hash="hashed")
    db_session.add(user)
    await db_session.flush()
    credentials = _credentials(expired=True)
    fernet = Fernet(key.encode("ascii"))
    row = GoogleOAuthConnection(
        user_id=user.id,
        encrypted_credentials=fernet.encrypt(credentials.to_json().encode()).decode("ascii"),
        scopes=[GMAIL_READONLY_SCOPE],
        expires_at=credentials.expiry.replace(tzinfo=UTC),
    )
    db_session.add(row)
    await db_session.commit()
    before = row.encrypted_credentials

    def refresh(instance, _request):
        instance.token = "rotated-access-token"
        instance.expiry = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)

    monkeypatch.setattr(Credentials, "refresh", refresh)
    token = await GoogleOAuthService(db_session).access_token(user.id)
    assert token == "rotated-access-token"
    assert row.encrypted_credentials != before


@pytest.mark.asyncio
async def test_gmail_oauth_revocation_calls_google_and_clears_encrypted_tokens(client, db_session, monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr("app.services.google_oauth.get_settings", lambda: _settings(key))
    headers = await _authenticated_client(client, "gmail-revoke@example.com")
    user = await db_session.scalar(select(User).where(User.email == "gmail-revoke@example.com"))
    credentials = _credentials()
    encrypted = Fernet(key.encode()).encrypt(credentials.to_json().encode()).decode()
    row = GoogleOAuthConnection(user_id=user.id, encrypted_credentials=encrypted, scopes=[GMAIL_READONLY_SCOPE], expires_at=credentials.expiry.replace(tzinfo=UTC))
    db_session.add(row)
    await db_session.commit()
    requested = {}

    class FakeResponse:
        status_code = 200

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, *, data):
            requested["url"] = url
            requested["token"] = data["token"]
            return FakeResponse()

    monkeypatch.setattr("app.services.google_oauth.httpx.AsyncClient", lambda **_kwargs: FakeClient())
    response = await client.delete("/api/v1/integrations/gmail/connection", headers=headers)
    assert response.status_code == 204
    assert requested["token"] == "test-refresh-token"
    await db_session.refresh(row)
    assert row.revoked_at is not None and row.encrypted_credentials == ""
    assert (await client.get("/api/v1/integrations/gmail/status", headers=headers)).json()["connected"] is False


def test_gmail_sender_allowlist_normalizes_and_rejects_invalid_addresses():
    from app.connectors.gmail_alerts import GmailJobAlertConnector

    assert GmailJobAlertConnector.normalize_sender_allowlist(["Careers@Example.org", "careers@example.org"]) == ["careers@example.org"]
    with pytest.raises(ConnectorNotConfigured, match="invalid address"):
        GmailJobAlertConnector.normalize_sender_allowlist(["example.org"])


@pytest.mark.asyncio
async def test_gmail_oauth_fails_closed_without_provider_configuration(client, monkeypatch):
    monkeypatch.setattr(
        "app.services.google_oauth.get_settings",
        lambda: SimpleNamespace(google_oauth_client_id=None, google_oauth_client_secret=None, google_oauth_redirect_uri=None, oauth_token_encryption_key=None),
    )
    headers = await _authenticated_client(client, "gmail-unconfigured@example.com")
    status = await client.get("/api/v1/integrations/gmail/status", headers=headers)
    assert status.status_code == 200
    assert status.json()["oauth_configured"] is False
    for category in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REDIRECT_URI", "OAUTH_TOKEN_ENCRYPTION_KEY"):
        assert category in status.json()["oauth_configuration_message"]
    response = await client.post("/api/v1/integrations/gmail/authorize", headers=headers)
    assert response.status_code == 503
    assert "Gmail connection is unavailable" in response.json()["detail"]
    assert "GOOGLE_OAUTH_CLIENT_SECRET" in response.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("redirect_uri", "encryption_key", "expected_category"),
    [
        ("http://app.example.test/api/v1/integrations/gmail/callback", Fernet.generate_key().decode("ascii"), "GOOGLE_OAUTH_REDIRECT_URI must be a valid HTTPS URL"),
        ("https://app.example.test/wrong-callback", Fernet.generate_key().decode("ascii"), "GOOGLE_OAUTH_REDIRECT_URI must be a valid HTTPS URL"),
        ("https://app.example.test:invalid/api/v1/integrations/gmail/callback", Fernet.generate_key().decode("ascii"), "GOOGLE_OAUTH_REDIRECT_URI must be a valid HTTPS URL"),
        ("https://app.example.test/api/v1/integrations/gmail/callback", "not-a-fernet-key", "OAUTH_TOKEN_ENCRYPTION_KEY must be a valid Fernet key"),
    ],
)
async def test_gmail_oauth_rejects_malformed_redirect_or_encryption_key(
    client, db_session, monkeypatch, redirect_uri, encryption_key, expected_category
):
    settings = _settings(encryption_key)
    settings.google_oauth_redirect_uri = redirect_uri
    monkeypatch.setattr("app.services.google_oauth.get_settings", lambda: settings)
    headers = await _authenticated_client(client, f"gmail-invalid-{abs(hash(expected_category + redirect_uri + encryption_key))}@example.com")

    status = await client.get("/api/v1/integrations/gmail/status", headers=headers)
    assert status.status_code == 200
    assert status.json()["oauth_configured"] is False
    assert expected_category in status.json()["oauth_configuration_message"]

    response = await client.post("/api/v1/integrations/gmail/authorize", headers=headers)
    assert response.status_code == 503
    assert expected_category in response.json()["detail"]
    assert await db_session.scalar(select(GoogleOAuthState)) is None


@pytest.mark.asyncio
async def test_gmail_connector_reads_only_allowlisted_alert_messages(db_session, monkeypatch):
    from app.connectors.gmail_alerts import GmailJobAlertConnector

    user = User(email="gmail-connector@example.com", password_hash="hashed")
    db_session.add(user)
    await db_session.flush()
    source = JobSource(
        user_id=user.id,
        name="Allowed Gmail alerts",
        source_type="GMAIL_ALERT",
        connector_type="GMAIL_ALERT",
        status=JobSourceStatus.ENABLED,
        is_enabled=True,
        configuration={"allowed_senders": ["careers@example.org"]},
    )
    db_session.add(source)
    await db_session.flush()
    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(
        google_oauth_client_id="client", google_oauth_client_secret="secret", google_oauth_redirect_uri="https://app.example.test/callback", oauth_token_encryption_key="key",
    ))

    async def access_token(self, _user_id):
        return "fixture-token"

    monkeypatch.setattr(GoogleOAuthService, "access_token", access_token)
    message = EmailMessage()
    message["From"] = "Career Alerts <careers@example.org>"
    message["Subject"] = "Python Engineer opening"
    message.set_content("Build Python APIs. View job: https://jobs.example.org/role/1")
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")
    requested = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, *, headers, params):
            requested.append((url, headers, params))
            return FakeResponse({"messages": [{"id": "message-1"}]} if url.endswith("/messages") else {"raw": raw})

    monkeypatch.setattr("app.connectors.gmail_alerts.httpx.AsyncClient", lambda **_kwargs: FakeClient())
    result = await GmailJobAlertConnector(source, db_session).fetch_jobs()
    assert result == []
    review = await db_session.scalar(select(GmailAlertReview).where(GmailAlertReview.gmail_message_id == "message-1"))
    assert review.status == "NEEDS_REVIEW"
    assert "company" in review.reason
    assert requested[0][1]["Authorization"] == "Bearer fixture-token"
    assert "from:careers@example.org" in requested[0][2]["q"]
