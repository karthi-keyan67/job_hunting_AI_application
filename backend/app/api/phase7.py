from datetime import date
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.dependencies import CurrentUser, SessionDep
from app.models.enums import ApplicationStatus, FollowUpStatus, InterviewStatus
from app.schemas.phase7 import ApplicationNotesUpdate, FollowUpCreate, FollowUpUpdate, InterviewCreate, InterviewUpdate
from app.services.dashboard import DashboardService
from app.services.phase7 import Phase7Service


dashboard_router = APIRouter(prefix="/dashboard", tags=["dashboard"])
analytics_router = APIRouter(prefix="/analytics", tags=["analytics"])
interviews_router = APIRouter(prefix="/interviews", tags=["interviews"])
follow_ups_router = APIRouter(prefix="/follow-ups", tags=["follow-ups"])
application_detail_router = APIRouter(prefix="/applications", tags=["applications"])


@dashboard_router.get("/summary")
async def dashboard_summary(user: CurrentUser, session: SessionDep, start_date: date | None = None, end_date: date | None = None):
    return await DashboardService(session).summary(user.id, start_date, end_date)


@dashboard_router.get("/recent-activity")
async def recent_activity(user: CurrentUser, session: SessionDep, limit: int = Query(default=20, ge=1, le=100)):
    return await DashboardService(session).repo.recent_activity(user.id, limit)


@dashboard_router.get("/upcoming")
async def upcoming(user: CurrentUser, session: SessionDep, limit: int = Query(default=20, ge=1, le=100)):
    return await DashboardService(session).repo.upcoming(user.id, limit=limit)


@dashboard_router.get("/pipeline")
async def pipeline(
    user: CurrentUser, session: SessionDep, search: str | None = Query(default=None, max_length=200),
    status_filter: ApplicationStatus | None = Query(default=None, alias="status"), date_from: date | None = None,
    date_to: date | None = None, location: str | None = Query(default=None, max_length=200),
    work_mode: str | None = Query(default=None, max_length=40), sort_by: str = Query(default="updated", pattern="^(updated|created|company|title)$"),
    offset: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100),
):
    return await DashboardService(session).pipeline(user.id, search=search, status=status_filter, date_from=date_from, date_to=date_to,
                                                    location=location, work_mode=work_mode, sort_by=sort_by, offset=offset, limit=limit)


@analytics_router.get("/overview")
async def analytics_overview(user: CurrentUser, session: SessionDep, start_date: date | None = None, end_date: date | None = None):
    return await DashboardService(session).analytics(user.id, start_date, end_date)


@analytics_router.get("/applications")
async def analytics_applications(user: CurrentUser, session: SessionDep, start_date: date | None = None, end_date: date | None = None):
    result = await DashboardService(session).analytics(user.id, start_date, end_date)
    return {key: result[key] for key in ("applications_by_status", "applications_over_time", "interview_conversion", "offer_conversion", "application_count", "date_range")}


@analytics_router.get("/matches")
async def analytics_matches(user: CurrentUser, session: SessionDep, start_date: date | None = None, end_date: date | None = None):
    result = await DashboardService(session).analytics(user.id, start_date, end_date)
    return {key: result[key] for key in ("jobs_collected_over_time", "match_distribution", "source_distribution", "date_range")}


@application_detail_router.get("/{application_id}/timeline")
async def application_timeline(application_id: UUID, user: CurrentUser, session: SessionDep):
    result = await DashboardService(session).repo.timeline(user.id, application_id)
    if result is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Application not found")
    return result


@application_detail_router.patch("/{application_id}/notes")
async def update_application_notes(application_id: UUID, payload: ApplicationNotesUpdate, user: CurrentUser, session: SessionDep):
    return await Phase7Service(session).update_notes(user.id, application_id, payload.notes)


@interviews_router.get("")
async def list_interviews(user: CurrentUser, session: SessionDep, application_id: UUID | None = None,
                          status_filter: InterviewStatus | None = Query(default=None, alias="status"), upcoming_only: bool | None = None,
                          offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=100)):
    return await Phase7Service(session).list_interviews(user.id, application_id=application_id, status=status_filter, upcoming=upcoming_only, offset=offset, limit=limit)


@interviews_router.post("", status_code=status.HTTP_201_CREATED)
async def create_interview(payload: InterviewCreate, user: CurrentUser, session: SessionDep):
    return await Phase7Service(session).create_interview(user.id, payload)


@interviews_router.get("/{interview_id}")
async def get_interview(interview_id: UUID, user: CurrentUser, session: SessionDep):
    return await Phase7Service(session).get_interview(user.id, interview_id)


@interviews_router.patch("/{interview_id}")
async def update_interview(interview_id: UUID, payload: InterviewUpdate, user: CurrentUser, session: SessionDep):
    return await Phase7Service(session).update_interview(user.id, interview_id, payload)


@interviews_router.delete("/{interview_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_interview(interview_id: UUID, user: CurrentUser, session: SessionDep):
    await Phase7Service(session).delete_interview(user.id, interview_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@follow_ups_router.get("")
async def list_follow_ups(user: CurrentUser, session: SessionDep, application_id: UUID | None = None,
                          status_filter: FollowUpStatus | None = Query(default=None, alias="status"), overdue: bool | None = None,
                          offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=100)):
    return await Phase7Service(session).list_follow_ups(user.id, application_id=application_id, status=status_filter, overdue=overdue, offset=offset, limit=limit)


@follow_ups_router.post("", status_code=status.HTTP_201_CREATED)
async def create_follow_up(payload: FollowUpCreate, user: CurrentUser, session: SessionDep):
    return await Phase7Service(session).create_follow_up(user.id, payload)


@follow_ups_router.patch("/{follow_up_id}")
async def update_follow_up(follow_up_id: UUID, payload: FollowUpUpdate, user: CurrentUser, session: SessionDep):
    return await Phase7Service(session).update_follow_up(user.id, follow_up_id, payload)


@follow_ups_router.delete("/{follow_up_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_follow_up(follow_up_id: UUID, user: CurrentUser, session: SessionDep):
    await Phase7Service(session).delete_follow_up(user.id, follow_up_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
