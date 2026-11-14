from uuid import UUID

from fastapi import APIRouter, Query

from app.api.dependencies import CurrentUser, SessionDep
from app.schemas.matching import MatchResult, MatchingResults, MatchingRunRequest, MatchingSummary
from app.services.matching import MatchingService

router = APIRouter(prefix="/matching", tags=["matching"])


@router.post("/run", response_model=MatchingResults)
async def run_matching(payload: MatchingRunRequest, user: CurrentUser, session: SessionDep):
    return await MatchingService(session).run(user.id, resume_version_id=payload.resume_version_id, job_ids=payload.job_ids, include_ai=payload.include_ai)


@router.post("/jobs/{job_id}", response_model=MatchResult)
async def match_one(job_id: UUID, payload: MatchingRunRequest, user: CurrentUser, session: SessionDep):
    return await MatchingService(session).one(user.id, job_id, resume_version_id=payload.resume_version_id, include_ai=payload.include_ai)


@router.post("/rematch", response_model=MatchingResults)
async def rematch(payload: MatchingRunRequest, user: CurrentUser, session: SessionDep):
    return await MatchingService(session).run(user.id, resume_version_id=payload.resume_version_id, job_ids=payload.job_ids, include_ai=payload.include_ai)


@router.get("/results", response_model=MatchingResults)
async def list_results(
    user: CurrentUser,
    session: SessionDep,
    min_score: float | None = Query(default=None, ge=0, le=100),
    location: str | None = Query(default=None, max_length=300),
    work_mode: str | None = Query(default=None, max_length=40),
    skill: str | None = Query(default=None, max_length=120),
    source_id: UUID | None = None,
    eligibility: str | None = Query(default=None, pattern="^(MATCH|PARTIAL_MATCH|MISMATCH|UNKNOWN)$"),
    recommendation: str | None = Query(default=None, pattern="^(STRONG_MATCH|REVIEW|LOW_MATCH|NOT_RECOMMENDED)$"),
    review_status: str | None = Query(default=None, pattern="^(PENDING|PENDING_REVIEW|APPROVED|APPROVED_FOR_PREPARATION|REJECTED|SAVED)$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
):
    return await MatchingService(session).results(user.id, min_score=min_score, location=location, work_mode=work_mode,
                                                  skill=skill, source_id=source_id, eligibility=eligibility,
                                                  recommendation=recommendation, review_status=review_status, offset=offset, limit=limit)


@router.get("/results/{match_id}", response_model=MatchResult)
async def get_result(match_id: UUID, user: CurrentUser, session: SessionDep):
    return await MatchingService(session).result(user.id, match_id)


@router.get("/summary", response_model=MatchingSummary)
async def matching_summary(user: CurrentUser, session: SessionDep):
    return await MatchingService(session).summary(user.id)
