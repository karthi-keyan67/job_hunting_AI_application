from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integrations import GmailAlertReview
from app.models.jobs import JobSource


class GmailAlertReviewService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list(self, user_id: UUID, status: str = "NEEDS_REVIEW", limit: int = 100) -> list[dict]:
        query = select(GmailAlertReview).where(GmailAlertReview.user_id == user_id)
        if status != "ALL":
            query = query.where(GmailAlertReview.status == status)
        rows = await self.session.scalars(query.order_by(GmailAlertReview.received_at.desc().nullslast()).limit(limit))
        return [{"id": str(row.id), "source_id": str(row.source_id), "subject": row.subject, "sender": row.sender,
                 "received_at": row.received_at, "status": row.status, "reason": row.reason, "excerpt": row.excerpt}
                for row in rows]

    async def update_status(self, user_id: UUID, item_id: UUID, status: str) -> dict:
        if status not in {"REVIEWED", "IGNORED"}:
            raise HTTPException(status_code=422, detail="Status must be REVIEWED or IGNORED")
        row = await self.session.scalar(select(GmailAlertReview).join(JobSource, JobSource.id == GmailAlertReview.source_id)
            .where(GmailAlertReview.id == item_id, GmailAlertReview.user_id == user_id, JobSource.user_id == user_id))
        if row is None:
            raise HTTPException(status_code=404, detail="Gmail alert review item not found")
        row.status = status
        await self.session.commit()
        return {"id": str(row.id), "status": row.status}
