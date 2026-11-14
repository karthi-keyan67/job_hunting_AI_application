from datetime import UTC, datetime
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.models.account import User
from app.models.applications import Notification
from app.models.applications import Application
from app.models.automation import AutomationExecution, AutomationSettings
from app.models.enums import JobSourceStatus, RunStatus
from app.models.jobs import CollectionRun, JobSource
from app.models.tracking import Interview
from app.services.automation import collect_sources, next_scheduled_run, process_reminders, scheduled_slot
from app.services.automation import _match_recent
from app.services.notifications import deliver_outbox, enqueue, in_quiet_hours


async def _auth(client, email="automation@example.com"):
    response = await client.post("/api/v1/auth/register", json={"email": email, "password": "correct-horse-battery-1"})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_six_hour_schedule_uses_ist_boundaries():
    now = datetime(2026, 11, 14, 0, 1, tzinfo=ZoneInfo("Asia/Kolkata"))
    next_run = next_scheduled_run(now)
    assert next_run.astimezone(ZoneInfo("Asia/Kolkata")).hour == 6
    assert next_run.astimezone(ZoneInfo("Asia/Kolkata")).minute == 0
    assert scheduled_slot(now).astimezone(ZoneInfo("Asia/Kolkata")).hour == 0


@pytest.mark.asyncio
async def test_automation_and_notification_preferences(client):
    headers = await _auth(client)
    current = await client.get("/api/v1/automation/settings", headers=headers)
    assert current.status_code == 200
    assert current.json()["timezone"] == "Asia/Kolkata"
    changed = await client.put("/api/v1/notifications/preferences", headers=headers, json={
        "enabled": True, "timezone": "Asia/Kolkata", "email_enabled": True, "notify_job_matches": True,
        "notify_collection": False, "notify_reminders": True, "minimum_match_score": 82,
        "quiet_start": "22:00", "quiet_end": "07:00", "reminder_intervals_minutes": [60, 1440],
    })
    assert changed.status_code == 200, changed.text
    assert changed.json()["minimum_match_score"] == 82
    invalid = await client.put("/api/v1/automation/settings", headers=headers, json={
        "timezone": "Mars/Olympus", "quiet_start": "22:00", "quiet_end": "07:00", "reminder_intervals_minutes": [60],
    })
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_manual_collection_is_authenticated_and_idempotent(client, db_session, session_factory, monkeypatch):
    monkeypatch.setattr("app.services.automation.SessionFactory", session_factory)
    unauthorized = await client.post("/api/v1/automation/collect", json={"source_ids": []})
    assert unauthorized.status_code == 401
    headers = await _auth(client)
    response = await client.post("/api/v1/automation/collect", headers=headers, json={"source_ids": []})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "SUCCEEDED"
    slot = scheduled_slot()
    assert (await collect_sources(slot))["status"] == "SUCCEEDED"
    duplicate = await collect_sources(slot)
    assert duplicate["status"] == "DUPLICATE"
    assert await db_session.scalar(select(AutomationExecution.id)) is not None
    history = await client.get("/api/v1/automation/collection-runs?offset=0&limit=10", headers=headers)
    assert history.status_code == 200 and history.json()["items"] == []
    monitoring = await client.get("/api/v1/monitoring", headers=headers)
    assert monitoring.status_code == 200 and "source_metrics" in monitoring.json()


@pytest.mark.asyncio
async def test_notifications_are_deduplicated_and_owner_scoped(client, db_session):
    first_headers = await _auth(client, "notice-one@example.com")
    second_headers = await _auth(client, "notice-two@example.com")
    first_id = (await db_session.scalar(select(User).where(User.email == "notice-one@example.com"))).id
    settings = await db_session.scalar(select(AutomationSettings).where(AutomationSettings.user_id == first_id))
    settings.email_enabled = False
    await db_session.flush()
    item = Notification(user_id=first_id, notification_type="HIGH_MATCH_JOB", payload={"title": "Strong match"}, dedupe_key="job-match:test", delivery_status="SKIPPED")
    db_session.add(item)
    await db_session.commit()
    first = await client.get("/api/v1/notifications", headers=first_headers)
    second = await client.get("/api/v1/notifications", headers=second_headers)
    assert len(first.json()["items"]) == 1
    assert second.json()["items"] == []
    wrong_owner = await client.patch(f"/api/v1/notifications/{item.id}/read", headers=second_headers)
    assert wrong_owner.status_code == 404
    marked = await client.patch(f"/api/v1/notifications/{item.id}/read", headers=first_headers)
    assert marked.status_code == 200 and marked.json()["is_read"] is True


@pytest.mark.asyncio
async def test_postgres_advisory_lock_has_single_owner(test_engine):
    from sqlalchemy import text
    first = await test_engine.connect()
    second = await test_engine.connect()
    try:
        assert await first.scalar(text("SELECT pg_try_advisory_lock(81024008)")) is True
        assert await second.scalar(text("SELECT pg_try_advisory_lock(81024008)")) is False
    finally:
        await first.execute(text("SELECT pg_advisory_unlock(81024008)"))
        await first.close()
        await second.close()


def test_quiet_hours_cross_midnight_in_user_timezone():
    from types import SimpleNamespace
    prefs = SimpleNamespace(timezone="Asia/Kolkata", quiet_start="22:00", quiet_end="07:00")
    assert in_quiet_hours(datetime(2026, 11, 14, 18, 0, tzinfo=UTC), prefs) is True
    assert in_quiet_hours(datetime(2026, 11, 14, 8, 0, tzinfo=UTC), prefs) is False


@pytest.mark.asyncio
async def test_outbox_retry_backoff_and_delivery(db_session, monkeypatch):
    user = User(email="outbox@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()
    prefs = AutomationSettings(user_id=user.id, email_enabled=True, timezone="Asia/Kolkata")
    db_session.add(prefs)
    await db_session.commit()
    item = await enqueue(db_session, user.id, "HIGH_MATCH_JOB", {"title": "Job alert"}, "retry-test")
    assert item is not None
    assert await enqueue(db_session, user.id, "HIGH_MATCH_JOB", {"title": "duplicate"}, "retry-test") is None

    from types import SimpleNamespace
    monkeypatch.setattr("app.services.notifications.get_settings", lambda: SimpleNamespace(smtp_host="smtp.test", smtp_from_email="noreply@test", smtp_port=587, smtp_starttls=True, smtp_username=None, smtp_password=None))
    def failed_send(*args):
        raise OSError("provider unavailable")
    monkeypatch.setattr("app.services.notifications._smtp_send", failed_send)
    assert await deliver_outbox(db_session) == 0
    await db_session.refresh(item)
    assert item.delivery_attempts == 1 and item.delivery_status == "PENDING"
    assert item.next_attempt_at > datetime.now(UTC)
    assert await deliver_outbox(db_session) == 0
    item.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    monkeypatch.setattr("app.services.notifications._smtp_send", lambda *args: None)
    assert await deliver_outbox(db_session) == 1
    await db_session.refresh(item)
    assert item.delivery_status == "DELIVERED" and item.delivered_at is not None


@pytest.mark.asyncio
async def test_collection_retries_one_source_without_blocking_others(db_session, session_factory, monkeypatch):
    from types import SimpleNamespace
    user = User(email="collector@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()
    broken = JobSource(user_id=user.id, name="Transient source", is_enabled=True, status=JobSourceStatus.ENABLED)
    healthy = JobSource(user_id=user.id, name="Healthy source", is_enabled=True, status=JobSourceStatus.ENABLED)
    db_session.add_all([broken, healthy])
    db_session.add(AutomationSettings(user_id=user.id, enabled=False))
    await db_session.commit()
    calls = {broken.id: 0, healthy.id: 0}

    async def fake_collect(self, source_id, user_id):
        calls[source_id] += 1
        if source_id == broken.id:
            raise RuntimeError("safe test failure")
        run = CollectionRun(source_id=source_id, status=RunStatus.SUCCEEDED)
        self.session.add(run)
        await self.session.commit()
        return run

    monkeypatch.setattr("app.services.automation.JobService.collect_source", fake_collect)
    monkeypatch.setattr("app.services.automation._match_recent", lambda *args: _no_matches())
    monkeypatch.setattr("app.services.automation.get_settings", lambda: SimpleNamespace(collection_retry_attempts=2, collection_timeout_seconds=30, matching_max_batch=10, automation_timezone="Asia/Kolkata"))
    monkeypatch.setattr("app.services.automation.SessionFactory", session_factory)
    result = await collect_sources(datetime.now(UTC).replace(second=0, microsecond=0), source_ids=[broken.id, healthy.id])
    assert result["status"] == "PARTIAL"
    assert calls == {broken.id: 2, healthy.id: 1}
    assert [row["status"] for row in result["results"]] == ["FAILED", "SUCCEEDED"]


@pytest.mark.asyncio
async def test_collection_timeout_marks_durable_run_failed(db_session, session_factory, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    user = User(email="timeout-collector@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()
    source = JobSource(user_id=user.id, name="Slow source", is_enabled=True, status=JobSourceStatus.ENABLED)
    db_session.add(source)
    await db_session.commit()

    async def slow_collect(self, source_id, user_id):
        run = CollectionRun(source_id=source_id, status=RunStatus.RUNNING)
        self.session.add(run)
        await self.session.commit()
        await asyncio.sleep(5)
        return run

    monkeypatch.setattr("app.services.automation.JobService.collect_source", slow_collect)
    monkeypatch.setattr("app.services.automation.SessionFactory", session_factory)
    monkeypatch.setattr("app.services.automation.get_settings", lambda: SimpleNamespace(collection_retry_attempts=1, collection_timeout_seconds=0.5, matching_max_batch=10, automation_timezone="Asia/Kolkata"))
    result = await collect_sources(datetime.now(UTC), source_ids=[source.id])
    assert result["status"] == "FAILED"
    run = await db_session.scalar(select(CollectionRun).where(CollectionRun.source_id == source.id))
    assert run.status == RunStatus.FAILED
    assert run.error_summary == "Collection timed out"


@pytest.mark.asyncio
async def test_interview_reminder_is_created_once(client, db_session, session_factory, monkeypatch):
    monkeypatch.setattr("app.services.automation.SessionFactory", session_factory)
    headers = await _auth(client, "reminder@example.com")
    user = await db_session.scalar(select(User).where(User.email == "reminder@example.com"))
    imported = await client.post("/api/v1/jobs/import", headers=headers, json={"title": "Engineer", "company_name": "Example Co", "description": "Build systems."})
    assert imported.status_code == 201, imported.text
    application = Application(user_id=user.id, job_id=imported.json()["id"])
    db_session.add(application)
    await db_session.flush()
    scheduled = datetime.now(UTC) + timedelta(minutes=60, seconds=30)
    db_session.add(Interview(user_id=user.id, application_id=application.id, interview_type="Technical", scheduled_at=scheduled, timezone="Asia/Kolkata"))
    prefs = await db_session.scalar(select(AutomationSettings).where(AutomationSettings.user_id == user.id))
    prefs.timezone = "Asia/Kolkata"
    prefs.reminder_intervals_minutes = [60]
    prefs.notify_reminders = True
    await db_session.commit()
    assert await process_reminders() == 1
    assert await process_reminders() == 0
    inbox = await client.get("/api/v1/notifications", headers=headers)
    assert [item["notification_type"] for item in inbox.json()["items"]] == ["INTERVIEW_REMINDER"]


@pytest.mark.asyncio
async def test_collected_jobs_flow_into_existing_matching_and_alerts(client, db_session, session_factory, monkeypatch):
    from types import SimpleNamespace
    from uuid import UUID, uuid4
    from app.services.matching import MatchingService

    headers = await _auth(client, "automatic-match@example.com")
    user = await db_session.scalar(select(User).where(User.email == "automatic-match@example.com"))
    collection_started = datetime.now(UTC) - timedelta(minutes=1)
    job_response = await client.post("/api/v1/jobs/import", headers=headers, json={"title": "Senior Python Engineer", "company_name": "Example", "description": "Python backend."})
    assert job_response.status_code == 201
    job_id = job_response.json()["id"]
    prefs = await db_session.scalar(select(AutomationSettings).where(AutomationSettings.user_id == user.id))
    prefs.notify_job_matches = True
    prefs.minimum_match_score = 80
    await db_session.commit()
    called = []

    async def fake_match(self, user_id, **kwargs):
        called.append(kwargs)
        return {"items": [{"id": str(uuid4()), "job_id": job_id, "overall_score": 88, "job": {"title": "Senior Python Engineer", "company_name": "Example"}}]}

    monkeypatch.setattr(MatchingService, "run", fake_match)
    monkeypatch.setattr("app.services.automation.SessionFactory", session_factory)
    monkeypatch.setattr("app.services.automation.get_settings", lambda: SimpleNamespace(matching_max_batch=10, automation_timezone="Asia/Kolkata"))
    assert await _match_recent(user.id, UUID(job_response.json()["source_id"]), collection_started) == 1
    assert called and called[0]["include_ai"] is True
    inbox = await client.get("/api/v1/notifications", headers=headers)
    assert inbox.json()["items"][0]["notification_type"] == "HIGH_MATCH_JOB"


async def _no_matches():
    return 0
