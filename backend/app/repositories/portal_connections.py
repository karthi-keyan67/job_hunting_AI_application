from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integrations import IntegrationAuditLog
from app.models.jobs import CollectionRun, JobSource


class PortalConnectionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def alert_sources(self, user_id: UUID) -> list[JobSource]:
        rows = await self.session.scalars(
            select(JobSource)
            .where(JobSource.user_id == user_id, JobSource.source_type == "GMAIL_ALERT")
            .order_by(JobSource.created_at.desc())
        )
        return [row for row in rows if str((row.configuration or {}).get("platform", "")).upper() in {
            "LINKEDIN", "NAUKRI", "INDEED", "INSTAHYRE", "CUTSHORT", "HIRIST"
        }]

    async def source_for_platform(self, user_id: UUID, platform: str) -> JobSource | None:
        rows = await self.alert_sources(user_id)
        return next((row for row in rows if str(row.configuration.get("platform", "")).upper() == platform), None)

    async def runs(self, source_id: UUID, limit: int = 10) -> list[CollectionRun]:
        rows = await self.session.scalars(
            select(CollectionRun).where(CollectionRun.source_id == source_id)
            .order_by(desc(CollectionRun.started_at)).limit(limit)
        )
        return list(rows)

    async def audit(self, user_id: UUID, *, platform: str | None = None, limit: int = 50, offset: int = 0) -> list[IntegrationAuditLog]:
        query = select(IntegrationAuditLog).where(IntegrationAuditLog.user_id == user_id)
        if platform:
            query = query.where(IntegrationAuditLog.platform == platform)
        rows = await self.session.scalars(query.order_by(desc(IntegrationAuditLog.occurred_at)).offset(offset).limit(limit))
        return list(rows)


def record_integration_event(session: AsyncSession, user_id: UUID, platform: str, action: str,
                             *, source_id: UUID | None = None, details: dict | None = None) -> None:
    session.add(IntegrationAuditLog(user_id=user_id, source_id=source_id, platform=platform,
                                    action=action, details=details or {}))
