import pytest
from sqlalchemy import select

from app.models import AuthLoginAttempt, JobPreference, User, UserProfile
from app.core.config import Settings
from app.services.auth import password_hasher


async def register(client, email="dev@example.com", password="correct-horse-battery-1"):
    return await client.post("/api/v1/auth/register", json={"email": email, "password": password})


@pytest.mark.asyncio
async def test_register_hashes_password_and_creates_profile_and_preferences(client, db_session):
    response = await register(client)
    assert response.status_code == 201
    user = await db_session.scalar(select(User).where(User.email == "dev@example.com"))
    assert user is not None
    assert user.password_hash != "correct-horse-battery-1"
    assert password_hasher.verify("correct-horse-battery-1", user.password_hash)
    assert await db_session.scalar(select(UserProfile).where(UserProfile.user_id == user.id)) is not None
    assert await db_session.scalar(select(JobPreference).where(JobPreference.user_id == user.id)) is not None


@pytest.mark.asyncio
async def test_duplicate_email_rejected_case_insensitively(client):
    assert (await register(client, "Dev@Example.com")).status_code == 201
    response = await register(client, "dev@example.com")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_login_success_and_failure(client):
    await register(client)
    success = await client.post("/api/v1/auth/login", json={"email": "DEV@example.com", "password": "correct-horse-battery-1"})
    failure = await client.post("/api/v1/auth/login", json={"email": "dev@example.com", "password": "wrong-password"})
    assert success.status_code == 200
    assert success.json()["token_type"] == "bearer"
    assert failure.status_code == 401


@pytest.mark.asyncio
async def test_login_attempts_are_rate_limited_without_storing_email_or_ip(client, db_session, monkeypatch):
    monkeypatch.setattr("app.services.auth.settings.auth_login_max_attempts", 2)
    registration = await register(client, "throttle@example.com")
    assert registration.status_code == 201
    for _ in range(2):
        failed = await client.post("/api/v1/auth/login", json={"email": "throttle@example.com", "password": "incorrect-password"})
        assert failed.status_code == 401
    limited = await client.post("/api/v1/auth/login", json={"email": "throttle@example.com", "password": "incorrect-password"})
    assert limited.status_code == 429
    record = await db_session.scalar(select(AuthLoginAttempt))
    assert record is not None and len(record.key_hash) == 64 and record.attempts == 3
    assert "throttle@example.com" not in record.key_hash and "127.0.0.1" not in record.key_hash


def test_production_configuration_rejects_development_secret_and_http_origins():
    with pytest.raises(ValueError):
        Settings(app_env="production", jwt_secret="replace-this-development-secret-before-deploying", postgres_password="strong-password", cors_origins="https://app.example.com")
    with pytest.raises(ValueError):
        Settings(app_env="production", jwt_secret="a" * 64, postgres_password="strong-password", cors_origins="http://localhost:5173")
    production = Settings(app_env="production", jwt_secret="a" * 64, postgres_password="strong-password", cors_origins="https://app.example.com")
    assert production.app_env == "production"


@pytest.mark.asyncio
async def test_jwt_protects_me_endpoint(client):
    unauthorized = await client.get("/api/v1/auth/me")
    tokens = (await register(client)).json()
    authorized = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert authorized.json()["email"] == "dev@example.com"


@pytest.mark.asyncio
async def test_refresh_rotates_and_revokes_previous_token(client):
    tokens = (await register(client)).json()
    refreshed = await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    new_refresh = refreshed.json()["refresh_token"]
    assert new_refresh != tokens["refresh_token"]
    replay = await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert replay.status_code == 401
    family_revoked = await client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh})
    assert family_revoked.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_refresh_token_family(client):
    tokens = (await register(client)).json()
    logout = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    reused = await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert logout.status_code == 204
    assert reused.status_code == 401


@pytest.mark.asyncio
async def test_health_checks_database(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
