from fastapi import APIRouter, Query, Response, status

from app.api.dependencies import CurrentUser, SessionDep
from app.services.google_oauth import GoogleOAuthService

router = APIRouter(prefix="/integrations/gmail", tags=["Gmail OAuth"])


@router.get("/status")
async def gmail_status(user: CurrentUser, session: SessionDep):
    return await GoogleOAuthService(session).status(user.id)


@router.post("/authorize")
async def gmail_authorize(user: CurrentUser, session: SessionDep):
    return await GoogleOAuthService(session).authorize(user.id)


@router.get("/callback")
async def gmail_callback(
    session: SessionDep,
    state: str | None = Query(default=None, max_length=512),
    code: str | None = Query(default=None, max_length=4096),
    error: str | None = Query(default=None, max_length=100),
):
    return await GoogleOAuthService(session).callback(state, code, error)


@router.delete("/connection", status_code=status.HTTP_204_NO_CONTENT)
async def gmail_revoke(user: CurrentUser, session: SessionDep):
    await GoogleOAuthService(session).revoke(user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
