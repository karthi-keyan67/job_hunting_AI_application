from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.auth import router as auth_router
from app.api.profile import router as profile_router
from app.api.resumes import router as resumes_router
from app.api.jobs import jobs_router, runs_router, sources_router
from app.api.matching import router as matching_router
from app.api.applications import applications_router, reviews_router
from app.api.dependencies import SessionDep
from app.api.phase7 import dashboard_router, analytics_router, interviews_router, follow_ups_router, application_detail_router
from app.api.automation import automation_router, notifications_router, monitoring_router
from app.api.google_oauth import router as google_oauth_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(profile_router)
router.include_router(resumes_router)
router.include_router(sources_router)
router.include_router(jobs_router)
router.include_router(runs_router)
router.include_router(matching_router)
router.include_router(reviews_router)
router.include_router(applications_router)
router.include_router(dashboard_router)
router.include_router(analytics_router)
router.include_router(interviews_router)
router.include_router(follow_ups_router)
router.include_router(application_detail_router)
router.include_router(automation_router)
router.include_router(notifications_router)
router.include_router(monitoring_router)
router.include_router(google_oauth_router)


@router.get("/health", tags=["health"])
async def health(session: SessionDep) -> dict[str, str]:
    """Report API and database readiness."""
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ok", "database": "ok"}
