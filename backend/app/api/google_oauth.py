from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, Field

from app.api.dependencies import CurrentUser, SessionDep
from app.services.google_oauth import GoogleOAuthService
from app.services.gmail_alerts import GmailAlertReviewService

router = APIRouter(prefix="/integrations/gmail", tags=["Gmail OAuth"])


class ReviewStatusUpdate(BaseModel):
    status: str = Field(pattern="^(REVIEWED|IGNORED)$")


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


@router.get("/reviews")
async def gmail_reviews(user: CurrentUser, session: SessionDep, status_filter: str = Query(default="NEEDS_REVIEW", alias="status", pattern="^(NEEDS_REVIEW|REVIEWED|IGNORED|FILTERED|ALL)$"), limit: int = Query(default=100, ge=1, le=200)):
    return await GmailAlertReviewService(session).list(user.id, status_filter, limit)


@router.patch("/reviews/{review_id}")
async def update_gmail_review(review_id: UUID, payload: ReviewStatusUpdate, user: CurrentUser, session: SessionDep):
    return await GmailAlertReviewService(session).update_status(user.id, review_id, payload.status)
