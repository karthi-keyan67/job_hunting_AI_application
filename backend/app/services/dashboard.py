from datetime import date
from uuid import UUID

from fastapi import HTTPException

from app.models.enums import ApplicationStatus
from app.repositories.dashboard import DashboardRepository
from app.services.applications import application_view


class DashboardService:
    def __init__(self, session):
        self.repo = DashboardRepository(session)

    @staticmethod
    def validate_range(start_date: date | None, end_date: date | None):
        if start_date and end_date and start_date > end_date:
            raise HTTPException(status_code=422, detail="start_date must be on or before end_date")

    async def summary(self, user_id: UUID, start_date: date | None, end_date: date | None):
        self.validate_range(start_date, end_date)
        metrics = await self.repo.summary(user_id, start_date, end_date)
        metrics["recent_activity"] = await self.repo.recent_activity(user_id, 10)
        metrics["recent_matching_results"] = await self.repo.recent_matches(user_id, 8)
        metrics["upcoming"] = await self.repo.upcoming(user_id, limit=10)
        return metrics

    async def pipeline(self, user_id: UUID, *, search, status, date_from, date_to, location, work_mode, sort_by, offset, limit):
        if date_from and date_to and date_from > date_to:
            raise HTTPException(status_code=422, detail="date_from must be on or before date_to")
        page = await self.repo.pipeline(user_id, search=search, status=status, date_from=date_from, date_to=date_to,
                                        location=location, work_mode=work_mode, sort_by=sort_by, offset=offset, limit=limit)
        page["items"] = [application_view(application) for application in page["items"]]
        return page

    async def analytics(self, user_id: UUID, start_date: date | None, end_date: date | None):
        self.validate_range(start_date, end_date)
        return await self.repo.analytics(user_id, start_date, end_date)
