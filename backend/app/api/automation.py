from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.api.dependencies import CurrentUser, SessionDep
from app.repositories.automation import AutomationRepository
from app.schemas.automation import AutomationSettingsUpdate, ManualCollectionRequest
from app.services.automation_api import AutomationAPIService

automation_router = APIRouter(prefix="/automation", tags=["automation"])
notifications_router = APIRouter(prefix="/notifications", tags=["notifications"])
monitoring_router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@automation_router.get("/settings")
async def automation_settings(user: CurrentUser, session: SessionDep):
    return await AutomationAPIService(session).settings(user.id)


@automation_router.put("/settings")
async def update_automation_settings(payload: AutomationSettingsUpdate, user: CurrentUser, session: SessionDep):
    return await AutomationAPIService(session).update_settings(user.id, payload.model_dump())


@automation_router.get("/status")
async def automation_status(user: CurrentUser, session: SessionDep):
    return await AutomationAPIService(session).status(user.id)


@automation_router.get("/collection-runs")
async def collection_history(user: CurrentUser, session: SessionDep, offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100)):
    from app.services.jobs import JobService
    rows = await JobService(session).all_runs(user.id)
    items = rows[offset:offset + limit]
    return {"items": [{"id": row.id, "source_id": row.source_id, "started_at": row.started_at, "completed_at": row.completed_at,
        "status": row.status.value, "jobs_found": row.jobs_found, "jobs_created": row.jobs_created, "jobs_updated": row.jobs_updated,
        "jobs_skipped": row.jobs_skipped, "duration_seconds": row.duration_seconds, "retry_count": row.retry_count,
        "matching_duration_seconds": row.matching_duration_seconds, "matching_failed": row.matching_failed,
        "error_summary": row.error_summary} for row in items], "total": len(rows), "offset": offset, "limit": limit}


@automation_router.post("/collect")
async def manual_collection(payload: ManualCollectionRequest, user: CurrentUser, session: SessionDep):
    return await AutomationAPIService(session).manual_collect(user.id, payload.source_ids)


@notifications_router.get("")
async def notification_inbox(user: CurrentUser, session: SessionDep, unread_only: bool = False, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    result = await AutomationRepository(session).notifications(user.id, unread_only=unread_only, offset=offset, limit=limit)
    result["items"] = [{"id": row.id, "notification_type": row.notification_type, "payload": row.payload, "is_read": row.is_read,
        "delivery_status": row.delivery_status, "delivery_attempts": row.delivery_attempts, "delivered_at": row.delivered_at, "created_at": row.created_at} for row in result["items"]]
    return result


@notifications_router.get("/preferences")
async def notification_preferences(user: CurrentUser, session: SessionDep):
    return await AutomationAPIService(session).settings(user.id)


@notifications_router.put("/preferences")
async def update_notification_preferences(payload: AutomationSettingsUpdate, user: CurrentUser, session: SessionDep):
    return await AutomationAPIService(session).update_settings(user.id, payload.model_dump())


@notifications_router.get("/reminder-settings")
async def reminder_settings(user: CurrentUser, session: SessionDep):
    return await AutomationAPIService(session).settings(user.id)


@notifications_router.patch("/{notification_id}/read")
async def mark_notification_read(notification_id: UUID, user: CurrentUser, session: SessionDep):
    row = await AutomationRepository(session).mark_read(user.id, notification_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"id": row.id, "is_read": row.is_read}


@notifications_router.get("/delivery-history")
async def notification_delivery_history(user: CurrentUser, session: SessionDep, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    result = await AutomationRepository(session).notifications(user.id, offset=offset, limit=limit)
    result["items"] = [{"id": row.id, "type": row.notification_type, "status": row.delivery_status,
        "attempts": row.delivery_attempts, "last_error": row.last_delivery_error, "created_at": row.created_at, "delivered_at": row.delivered_at} for row in result["items"]]
    return result


@monitoring_router.get("")
async def monitoring(user: CurrentUser, session: SessionDep):
    status = await AutomationAPIService(session).status(user.id)
    return {**status,
        "email_delivery": [{"status": item.delivery_status, "attempts": item.delivery_attempts, "created_at": item.created_at, "delivered_at": item.delivered_at}
            for item in (await AutomationRepository(session).notifications(user.id, limit=100))["items"]]}
