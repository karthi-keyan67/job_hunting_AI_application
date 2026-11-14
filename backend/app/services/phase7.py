from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select

from app.models.applications import Application, ApplicationAuditLog
from app.models.enums import FollowUpStatus, InterviewStatus
from app.models.tracking import FollowUp, Interview
from app.repositories.dashboard import DashboardRepository


def item_view(item):
    values = {column.name: getattr(item, column.name) for column in item.__table__.columns}
    return values


class Phase7Service:
    def __init__(self, session):
        self.session = session
        self.dashboard = DashboardRepository(session)

    async def owned_application(self, user_id: UUID, application_id: UUID):
        application = await self.session.scalar(select(Application).where(Application.id == application_id, Application.user_id == user_id))
        if application is None:
            raise HTTPException(status_code=404, detail="Application not found")
        return application

    async def _owned_item(self, model, item_id: UUID, user_id: UUID):
        item = await self.session.scalar(select(model).where(model.id == item_id, model.user_id == user_id))
        if item is None:
            raise HTTPException(status_code=404, detail="Record not found")
        return item

    async def _audit(self, application_id: UUID, user_id: UUID, action: str, details: dict):
        self.session.add(ApplicationAuditLog(application_id=application_id, actor_user_id=user_id, action=action, details=details))

    async def create_interview(self, user_id: UUID, payload):
        await self.owned_application(user_id, payload.application_id)
        item = Interview(user_id=user_id, **payload.model_dump())
        self.session.add(item)
        await self.session.flush()
        await self._audit(payload.application_id, user_id, "INTERVIEW_SCHEDULED", {"interview_id": str(item.id), "interview_type": payload.interview_type, "scheduled_at": payload.scheduled_at.isoformat()})
        await self.session.commit()
        await self.session.refresh(item)
        return item_view(item)

    async def list_interviews(self, user_id: UUID, *, application_id=None, status=None, upcoming=None, offset=0, limit=50):
        query = select(Interview).where(Interview.user_id == user_id)
        if application_id:
            query = query.where(Interview.application_id == application_id)
        if status:
            query = query.where(Interview.status == status)
        if upcoming is True:
            query = query.where(Interview.scheduled_at >= datetime.now(UTC), Interview.status == InterviewStatus.SCHEDULED)
        elif upcoming is False:
            query = query.where(Interview.scheduled_at < datetime.now(UTC))
        total = await self.session.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
        rows = list(await self.session.scalars(query.order_by(Interview.scheduled_at).offset(offset).limit(limit)))
        return {"items": [item_view(row) for row in rows], "total": int(total), "offset": offset, "limit": limit}

    async def get_interview(self, user_id: UUID, interview_id: UUID):
        return item_view(await self._owned_item(Interview, interview_id, user_id))

    async def update_interview(self, user_id: UUID, interview_id: UUID, payload):
        item = await self._owned_item(Interview, interview_id, user_id)
        values = payload.model_dump(exclude_unset=True)
        if not values:
            return item_view(item)
        if item.status == InterviewStatus.CANCELLED:
            raise HTTPException(status_code=409, detail="Cancelled interviews cannot be edited")
        for key, value in values.items():
            setattr(item, key, value)
        action = "INTERVIEW_CANCELLED" if values.get("status") == InterviewStatus.CANCELLED else ("INTERVIEW_COMPLETED" if values.get("status") == InterviewStatus.COMPLETED else "INTERVIEW_UPDATED")
        await self._audit(item.application_id, user_id, action, {"interview_id": str(item.id), "changed_fields": sorted(values)})
        await self.session.commit()
        await self.session.refresh(item)
        return item_view(item)

    async def delete_interview(self, user_id: UUID, interview_id: UUID):
        item = await self._owned_item(Interview, interview_id, user_id)
        if item.status != InterviewStatus.CANCELLED:
            item.status = InterviewStatus.CANCELLED
            await self._audit(item.application_id, user_id, "INTERVIEW_CANCELLED", {"interview_id": str(item.id), "cancelled_via_delete": True})
            await self.session.commit()

    async def create_follow_up(self, user_id: UUID, payload):
        await self.owned_application(user_id, payload.application_id)
        item = FollowUp(user_id=user_id, **payload.model_dump())
        self.session.add(item)
        await self.session.flush()
        await self._audit(payload.application_id, user_id, "FOLLOW_UP_CREATED", {"follow_up_id": str(item.id), "title": payload.title, "due_at": payload.due_at.isoformat()})
        await self.session.commit()
        await self.session.refresh(item)
        return item_view(item)

    async def list_follow_ups(self, user_id: UUID, *, application_id=None, status=None, overdue=None, offset=0, limit=50):
        query = select(FollowUp).where(FollowUp.user_id == user_id)
        if application_id:
            query = query.where(FollowUp.application_id == application_id)
        if status:
            query = query.where(FollowUp.status == status)
        if overdue is True:
            query = query.where(FollowUp.due_at < datetime.now(UTC), FollowUp.status == FollowUpStatus.PENDING)
        total = await self.session.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
        rows = list(await self.session.scalars(query.order_by(FollowUp.due_at).offset(offset).limit(limit)))
        return {"items": [item_view(row) for row in rows], "total": int(total), "offset": offset, "limit": limit}

    async def update_follow_up(self, user_id: UUID, follow_up_id: UUID, payload):
        item = await self._owned_item(FollowUp, follow_up_id, user_id)
        values = payload.model_dump(exclude_unset=True)
        if not values:
            return item_view(item)
        if item.status == FollowUpStatus.CANCELLED:
            raise HTTPException(status_code=409, detail="Cancelled follow-ups cannot be edited")
        if values.get("status") == FollowUpStatus.COMPLETED:
            item.completed_at = datetime.now(UTC)
        elif values.get("status") == FollowUpStatus.PENDING:
            item.completed_at = None
        for key, value in values.items():
            setattr(item, key, value)
        action = "FOLLOW_UP_COMPLETED" if item.status == FollowUpStatus.COMPLETED else "FOLLOW_UP_UPDATED"
        await self._audit(item.application_id, user_id, action, {"follow_up_id": str(item.id), "changed_fields": sorted(values)})
        await self.session.commit()
        await self.session.refresh(item)
        return item_view(item)

    async def delete_follow_up(self, user_id: UUID, follow_up_id: UUID):
        item = await self._owned_item(FollowUp, follow_up_id, user_id)
        if item.status != FollowUpStatus.CANCELLED:
            item.status = FollowUpStatus.CANCELLED
            await self._audit(item.application_id, user_id, "FOLLOW_UP_CANCELLED", {"follow_up_id": str(item.id), "cancelled_via_delete": True})
            await self.session.commit()

    async def update_notes(self, user_id: UUID, application_id: UUID, notes: str | None):
        application = await self.owned_application(user_id, application_id)
        application.notes = notes
        await self._audit(application_id, user_id, "APPLICATION_NOTES_UPDATED", {"notes_present": bool(notes)})
        await self.session.commit()
        return {"application_id": application_id, "notes": application.notes}
