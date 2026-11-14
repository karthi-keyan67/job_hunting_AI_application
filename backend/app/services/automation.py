import asyncio
import logging
from time import perf_counter
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.models.account import JobPreference
from app.models.automation import AutomationExecution, AutomationSettings, WorkerHeartbeat
from app.models.enums import RunStatus
from app.models.jobs import CollectionRun, Job, JobSource
from app.services.jobs import JobService
from app.services.matching import MatchingService
from app.services.notifications import deliver_outbox, enqueue

logger = logging.getLogger(__name__)
WORKER_NAME = "job-collection-worker"


def next_scheduled_run(now: datetime | None = None, timezone: str | None = None) -> datetime:
    settings = get_settings()
    zone = ZoneInfo(timezone or settings.automation_timezone)
    local_now = (now or datetime.now(UTC)).astimezone(zone)
    candidates = [local_now.replace(hour=h, minute=0, second=0, microsecond=0) for h in (0, 6, 12, 18)]
    next_local = next((value for value in candidates if value > local_now), None)
    if next_local is None:
        next_local = (local_now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return next_local.astimezone(UTC)


def scheduled_slot(now: datetime | None = None, timezone: str | None = None) -> datetime:
    zone = ZoneInfo(timezone or get_settings().automation_timezone)
    local = (now or datetime.now(UTC)).astimezone(zone)
    hour = (local.hour // 6) * 6
    return local.replace(hour=hour, minute=0, second=0, microsecond=0).astimezone(UTC)


async def heartbeat(status: str, *, next_run: datetime | None = None, success: bool = False, details: dict | None = None):
    async with SessionFactory() as session:
        row = await session.scalar(select(WorkerHeartbeat).where(WorkerHeartbeat.worker_name == WORKER_NAME))
        if row is None:
            row = WorkerHeartbeat(worker_name=WORKER_NAME)
            session.add(row)
        row.status = status
        row.last_heartbeat_at = datetime.now(UTC)
        row.next_run_at = next_run
        if success:
            row.last_success_at = row.last_heartbeat_at
        row.details = details or {}
        await session.commit()


async def _match_recent(user_id: UUID, source_id: UUID, since: datetime):
    async with SessionFactory() as session:
        prefs = await session.scalar(select(JobPreference).where(JobPreference.user_id == user_id, JobPreference.is_active.is_(True)))
        if not prefs:
            return 0
        ids = list(await session.scalars(select(Job.id).where(Job.source_id == source_id, Job.updated_at >= since).order_by(Job.updated_at.desc()).limit(get_settings().matching_max_batch)))
        if not ids:
            return 0
        results = await MatchingService(session).run(user_id, job_ids=ids, include_ai=True)
        count = 0
        for match in results["items"]:
            settings = await session.scalar(select(AutomationSettings).where(AutomationSettings.user_id == user_id))
            if settings and settings.notify_job_matches and match["overall_score"] >= settings.minimum_match_score:
                await enqueue(session, user_id, "HIGH_MATCH_JOB", {"title": f"Strong job match: {match['job']['title']}", "message": f"{match['job']['company_name']} · {round(match['overall_score'])}% match", "job_id": str(match["job_id"]), "score": match["overall_score"]}, f"match:{match['id']}")
                count += 1
        await session.commit()
        return count


async def _fail_timed_out_run(source_id: UUID, attempt_started: datetime) -> CollectionRun | None:
    async with SessionFactory() as session:
        run = await session.scalar(select(CollectionRun).where(CollectionRun.source_id == source_id,
            CollectionRun.status == RunStatus.RUNNING, CollectionRun.started_at >= attempt_started).order_by(CollectionRun.started_at.desc()).limit(1).with_for_update())
        if run is not None:
            now = datetime.now(UTC)
            run.status = RunStatus.FAILED
            run.completed_at = now
            run.finished_at = now
            run.error_message = "Collection timed out"
            run.error_summary = "Collection timed out"
            await session.commit()
            await session.refresh(run)
        return run


async def collect_sources(scheduled_for: datetime, *, source_ids: list[UUID] | None = None) -> dict:
    run_key = "scheduled:" + scheduled_for.astimezone(UTC).strftime("%Y%m%dT%H%M") if source_ids is None else f"manual:{UUID(int=0)}:{datetime.now(UTC).isoformat()}"
    async with SessionFactory() as session:
        statement = insert(AutomationExecution).values(run_key=run_key, scheduled_for=scheduled_for, started_at=datetime.now(UTC), status="RUNNING").on_conflict_do_nothing(index_elements=[AutomationExecution.run_key]).returning(AutomationExecution.id)
        execution_id = await session.scalar(statement)
        if execution_id is None:
            return {"status": "DUPLICATE", "run_key": run_key, "results": []}
        await session.commit()
        q = select(JobSource.id, JobSource.user_id).where(JobSource.is_enabled.is_(True), JobSource.user_id.is_not(None))
        if source_ids is None:
            q = q.outerjoin(AutomationSettings, AutomationSettings.user_id == JobSource.user_id).where(
                or_(AutomationSettings.id.is_(None), AutomationSettings.enabled.is_(True)))
        if source_ids is not None:
            q = q.where(JobSource.id.in_(source_ids))
        sources = list((await session.execute(q)).all())

    results = []
    errors = []
    cfg = get_settings()
    for source_id, user_id in sources:
        started = datetime.now(UTC)
        run = None
        retry_count = 0
        for attempt in range(cfg.collection_retry_attempts):
            attempt_started = datetime.now(UTC)
            try:
                async with SessionFactory() as session:
                    run = await asyncio.wait_for(JobService(session).collect_source(source_id, user_id), timeout=cfg.collection_timeout_seconds)
                if run.status.value not in {"FAILED"}:
                    retry_count = attempt
                    break
                raise RuntimeError("Collection run failed")
            except Exception as exc:
                retry_count = attempt + 1
                if isinstance(exc, TimeoutError):
                    run = await _fail_timed_out_run(source_id, attempt_started)
                errors.append({"source_id": str(source_id), "error_type": type(exc).__name__, "attempt": attempt + 1})
                if attempt + 1 < cfg.collection_retry_attempts:
                    await asyncio.sleep(min(2 ** attempt, 8))
        status = run.status.value if run else "FAILED"
        if run is not None:
            async with SessionFactory() as session:
                persisted = await session.get(type(run), run.id)
                if persisted:
                    persisted.retry_count = retry_count
                    persisted.duration_seconds = (datetime.now(UTC) - started).total_seconds()
                    await session.commit()
        results.append({"source_id": str(source_id), "status": status, "retry_count": retry_count,
                        "duration_seconds": (datetime.now(UTC) - started).total_seconds()})
        if status in {"SUCCEEDED", "PARTIAL"}:
            matching_started = perf_counter()
            try:
                matched = await _match_recent(user_id, source_id, started)
                results[-1]["matches_notified"] = matched
            except Exception as exc:
                errors.append({"source_id": str(source_id), "error_type": f"Matching:{type(exc).__name__}"})
                results[-1]["matching_failed"] = True
            results[-1]["matching_duration_seconds"] = perf_counter() - matching_started
            if run is not None:
                async with SessionFactory() as session:
                    persisted = await session.get(type(run), run.id)
                    if persisted:
                        persisted.matching_duration_seconds = results[-1]["matching_duration_seconds"]
                        persisted.matching_failed = results[-1].get("matching_failed", False)
                        await session.commit()
        async with SessionFactory() as session:
            setting = await session.scalar(select(AutomationSettings).where(AutomationSettings.user_id == user_id))
            if setting and setting.notify_collection:
                auth_failure = bool(run and run.error_message and any(word in run.error_message.casefold() for word in ("authorization", "authentication", "credential", "oauth")))
                notification_type = "JOB_COLLECTION_COMPLETED" if status == "SUCCEEDED" else ("CONNECTOR_AUTH_FAILURE" if auth_failure else "JOB_COLLECTION_FAILED")
                title = "Connector authorization needs attention" if auth_failure else f"Job collection {status.lower()}"
                message = "A configured connector needs authorized access." if auth_failure else f"A configured source finished with status {status}."
                await enqueue(session, user_id, notification_type, {"title": title, "message": message, "source_id": str(source_id)}, f"collection:{source_id}:{scheduled_for.astimezone(UTC).isoformat()}")
                await session.commit()

    final_status = "FAILED" if sources and all(item["status"] == "FAILED" for item in results) else ("PARTIAL" if errors or any(item["status"] in {"FAILED", "PARTIAL"} for item in results) else "SUCCEEDED")
    async with SessionFactory() as session:
        record = await session.get(AutomationExecution, execution_id)
        now = datetime.now(UTC)
        record.status = final_status
        record.completed_at = now
        record.duration_seconds = (now - record.started_at).total_seconds()
        record.retry_count = max((item["retry_count"] for item in results), default=0)
        record.error_details = {"failures": errors[:50], "source_count": len(sources)}
        await session.commit()
    return {"status": final_status, "run_key": run_key, "results": results, "errors": errors}


async def process_reminders() -> int:
    from app.models.enums import FollowUpStatus, InterviewStatus
    from app.models.tracking import FollowUp, Interview
    now = datetime.now(UTC)
    count = 0
    async with SessionFactory() as session:
        settings_rows = list(await session.scalars(select(AutomationSettings).where(AutomationSettings.enabled.is_(True), AutomationSettings.notify_reminders.is_(True))))
        for prefs in settings_rows:
            for interval in prefs.reminder_intervals_minutes:
                start, end = now + timedelta(minutes=interval), now + timedelta(minutes=interval, seconds=60)
                interviews = list(await session.scalars(select(Interview).where(Interview.user_id == prefs.user_id, Interview.status == InterviewStatus.SCHEDULED, Interview.scheduled_at >= start, Interview.scheduled_at < end)))
                followups = list(await session.scalars(select(FollowUp).where(FollowUp.user_id == prefs.user_id, FollowUp.status == FollowUpStatus.PENDING, FollowUp.due_at >= start, FollowUp.due_at < end)))
                for row in interviews:
                    created = await enqueue(session, prefs.user_id, "INTERVIEW_REMINDER", {"title": "Upcoming interview", "message": f"{row.interview_type} interview is scheduled for {row.scheduled_at.isoformat()} ({row.timezone}).", "interview_id": str(row.id)}, f"interview-reminder:{row.id}:{interval}")
                    count += int(created is not None)
                for row in followups:
                    created = await enqueue(session, prefs.user_id, "FOLLOW_UP_REMINDER", {"title": "Upcoming follow-up", "message": f"{row.title} is due {row.due_at.isoformat()} ({row.timezone}).", "follow_up_id": str(row.id)}, f"follow-up-reminder:{row.id}:{interval}")
                    count += int(created is not None)
        await session.commit()
    return count


async def scheduler_loop():
    from app.core.database import engine
    from sqlalchemy import text
    connection = await engine.connect()
    acquired = await connection.scalar(text("SELECT pg_try_advisory_lock(81024008)"))
    if not acquired:
        await connection.close()
        logger.warning("Another scheduler holds the PostgreSQL lease")
        while True:
            await asyncio.sleep(60)
    await connection.commit()
    last_slot = None
    try:
        while True:
            now = datetime.now(UTC)
            next_run = next_scheduled_run(now)
            await heartbeat("RUNNING", next_run=next_run)
            await process_reminders()
            async with SessionFactory() as session:
                await deliver_outbox(session)
            slot = scheduled_slot(now)
            if last_slot is None:
                local_now = now.astimezone(ZoneInfo(get_settings().automation_timezone))
                if local_now.minute > 1:
                    last_slot = slot
            if slot != last_slot:
                last_slot = slot
                try:
                    result = await collect_sources(slot)
                    await heartbeat("RUNNING", next_run=next_scheduled_run(), success=result["status"] in {"SUCCEEDED", "PARTIAL"}, details={"last_run_status": result["status"], "source_count": len(result["results"])})
                except Exception as exc:
                    logger.error("Scheduled collection failed exception_type=%s", type(exc).__name__)
                    await notify_worker_failure(type(exc).__name__)
                    await heartbeat("DEGRADED", next_run=next_scheduled_run(), details={"last_error_type": type(exc).__name__})
            await asyncio.sleep(30)
    finally:
        await connection.execute(text("SELECT pg_advisory_unlock(81024008)"))
        await connection.commit()
        await connection.close()


async def notify_worker_failure(error_type: str):
    now = datetime.now(UTC)
    bucket = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0).isoformat()
    async with SessionFactory() as session:
        users = list(await session.scalars(select(AutomationSettings).where(AutomationSettings.enabled.is_(True), AutomationSettings.notify_collection.is_(True))))
        for prefs in users:
            await enqueue(session, prefs.user_id, "WORKER_FAILURE", {"title": "Automation worker needs attention", "message": "The collection scheduler reported an execution failure."}, f"worker-failure:{prefs.user_id}:{bucket}")
        await session.commit()
