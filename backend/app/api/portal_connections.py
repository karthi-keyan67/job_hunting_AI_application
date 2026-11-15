from fastapi import APIRouter, Query

from app.api.dependencies import CurrentUser, SessionDep
from app.schemas.portal_connections import AlertSourceUpdate, DiscoveryUpdate
from app.services.portal_connections import PortalConnectionsService

router = APIRouter(prefix="/integrations/job-portals", tags=["job portal connections"])


@router.get("")
async def portal_overview(user: CurrentUser, session: SessionDep):
    return await PortalConnectionsService(session).overview(user.id)


@router.put("/{platform}/alerts")
async def configure_portal_alerts(platform: str, payload: AlertSourceUpdate, user: CurrentUser, session: SessionDep):
    return await PortalConnectionsService(session).save_alert_source(user.id, platform, payload.model_dump())


@router.patch("/{platform}/discovery")
async def set_portal_discovery(platform: str, payload: DiscoveryUpdate, user: CurrentUser, session: SessionDep):
    return await PortalConnectionsService(session).set_discovery(user.id, platform, payload.enabled)


@router.get("/{platform}/history")
async def portal_sync_history(platform: str, user: CurrentUser, session: SessionDep,
                              limit: int = Query(default=20, ge=1, le=100)):
    return await PortalConnectionsService(session).history(user.id, platform, limit)


@router.get("/audit")
async def integration_audit(user: CurrentUser, session: SessionDep,
                            platform: str | None = Query(default=None, max_length=30),
                            offset: int = Query(default=0, ge=0),
                            limit: int = Query(default=50, ge=1, le=100)):
    return await PortalConnectionsService(session).audit(user.id, platform, limit, offset)
