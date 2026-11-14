from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.models.applications import Notification
from app.models.automation import AutomationExecution, AutomationSettings, WorkerHeartbeat
from app.models.jobs import CollectionRun, JobSource


class AutomationRepository:
    def __init__(self, session):
        self.session = session

    async def get_or_create_settings(self, user_id):
        row = await self.session.scalar(select(AutomationSettings).where(AutomationSettings.user_id == user_id))
        if row is None:
            row = AutomationSettings(user_id=user_id)
            self.session.add(row)
            await self.session.commit()
            await self.session.refresh(row)
        return row

    async def update_settings(self, user_id, values):
        row = await self.get_or_create_settings(user_id)
        for key, value in values.items():
            setattr(row, key, value)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def notifications(self, user_id, *, unread_only=False, offset=0, limit=50):
        query = select(Notification).where(Notification.user_id == user_id)
        if unread_only:
            query = query.where(Notification.is_read.is_(False))
        total = await self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = list(await self.session.scalars(query.order_by(Notification.created_at.desc()).offset(offset).limit(limit)))
        return {"items": rows, "total": int(total), "offset": offset, "limit": limit}

    async def mark_read(self, user_id, notification_id):
        row = await self.session.scalar(select(Notification).where(Notification.id == notification_id, Notification.user_id == user_id))
        if row is None:
            return None
        row.is_read = True
        await self.session.commit()
        return row

    async def worker_status(self):
        rows = list(await self.session.scalars(select(WorkerHeartbeat).order_by(WorkerHeartbeat.updated_at.desc()).limit(10)))
        return rows

    async def metrics(self, user_id):
        since = datetime.now(UTC) - timedelta(days=30)
        sources = list((await self.session.execute(select(JobSource.id, JobSource.name, JobSource.status, JobSource.last_success_at, JobSource.last_failure_at).where(JobSource.user_id == user_id))).all())
        run_rows = list((await self.session.execute(select(CollectionRun.source_id, CollectionRun.status, CollectionRun.retry_count,
            CollectionRun.duration_seconds, CollectionRun.matching_duration_seconds, CollectionRun.matching_failed)
            .join(JobSource, JobSource.id == CollectionRun.source_id).where(JobSource.user_id == user_id, CollectionRun.started_at >= since))).all())
        counts = {}
        for source_id, status, retries, duration, matching_duration, matching_failed in run_rows:
            bucket = counts.setdefault(source_id, {"success": 0, "failure": 0, "retry_count": 0, "collection_duration_seconds": [], "matching_duration_seconds": [], "matching_failures": 0})
            key = {"SUCCEEDED": "success", "PARTIAL": "partial", "FAILED": "failure"}.get(status.value, "failure")
            bucket[key] = bucket.get(key, 0) + 1
            bucket["retry_count"] += retries or 0
            if duration is not None: bucket["collection_duration_seconds"].append(duration)
            if matching_duration is not None: bucket["matching_duration_seconds"].append(matching_duration)
            bucket["matching_failures"] += int(matching_failed)
        result = []
        for row in sources:
            item = counts.get(row.id, {"success": 0, "partial": 0, "failure": 0, "retry_count": 0, "collection_duration_seconds": [], "matching_duration_seconds": [], "matching_failures": 0})
            item["collection_duration_average_seconds"] = round(sum(item["collection_duration_seconds"]) / len(item["collection_duration_seconds"]), 2) if item["collection_duration_seconds"] else None
            item["matching_duration_average_seconds"] = round(sum(item["matching_duration_seconds"]) / len(item["matching_duration_seconds"]), 2) if item["matching_duration_seconds"] else None
            item.pop("collection_duration_seconds"); item.pop("matching_duration_seconds")
            result.append({"id": str(row.id), "name": row.name, "status": row.status.value, "last_success_at": row.last_success_at, "last_failure_at": row.last_failure_at, **item})
        return {"sources": result}

    async def executions(self, limit=30):
        return list(await self.session.scalars(select(AutomationExecution).order_by(AutomationExecution.scheduled_for.desc()).limit(limit)))
