from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import get_settings
from app.models.jobs import JobSource
from app.repositories.automation import AutomationRepository
from app.services.automation import collect_sources, next_scheduled_run


class AutomationAPIService:
    def __init__(self, session):
        self.session = session
        self.repo = AutomationRepository(session)

    async def settings(self, user_id):
        row = await self.repo.get_or_create_settings(user_id)
        return self._settings_view(row)

    async def update_settings(self, user_id, values):
        row = await self.repo.update_settings(user_id, values)
        return self._settings_view(row)

    @staticmethod
    def _settings_view(row):
        return {"id": str(row.id), "enabled": row.enabled, "timezone": row.timezone, "schedule": "0,6,12,18 every day",
            "automation_timezone": get_settings().automation_timezone,
            "email_enabled": row.email_enabled, "email_provider_configured": bool(get_settings().smtp_host and get_settings().smtp_from_email),
            "notify_job_matches": row.notify_job_matches, "notify_collection": row.notify_collection,
            "notify_reminders": row.notify_reminders, "minimum_match_score": row.minimum_match_score,
            "quiet_start": row.quiet_start, "quiet_end": row.quiet_end,
            "reminder_intervals_minutes": row.reminder_intervals_minutes}

    async def manual_collect(self, user_id: UUID, source_ids: list[UUID]):
        query = select(JobSource.id).where(JobSource.user_id == user_id, JobSource.is_enabled.is_(True))
        if source_ids:
            query = query.where(JobSource.id.in_(source_ids))
        owned = set(await self.session.scalars(query))
        if source_ids and owned != set(source_ids):
            raise HTTPException(status_code=404, detail="One or more enabled sources were not found")
        return await collect_sources(datetime.now(UTC), source_ids=list(owned))

    async def status(self, user_id):
        settings = await self.repo.get_or_create_settings(user_id)
        workers = await self.repo.worker_status()
        worker = next((item for item in workers if item.worker_name == "job-collection-worker"), None)
        now = datetime.now(UTC)
        fresh = bool(worker and (now - worker.last_heartbeat_at).total_seconds() < 180)
        return {"enabled": settings.enabled, "timezone": get_settings().automation_timezone, "user_timezone": settings.timezone, "schedule": "0,6,12,18 every day",
            "scheduler_status": worker.status if fresh else "OFFLINE", "worker_heartbeat_at": worker.last_heartbeat_at if worker else None,
            "last_success_at": worker.last_success_at if worker else None, "next_scheduled_run": next_scheduled_run(now),
            "source_metrics": await self.repo.metrics(user_id)}
