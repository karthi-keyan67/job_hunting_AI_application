from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.dependencies import CurrentUser, SessionDep
from app.schemas.jobs import CollectionRunResponse, JobImport, JobListResponse, JobResponse, JobSourceCreate, JobSourcePatch, JobSourceResponse
from app.services.jobs import JobService, source_response

sources_router = APIRouter(prefix="/sources", tags=["job sources"])
jobs_router = APIRouter(prefix="/jobs", tags=["jobs"])
runs_router = APIRouter(prefix="/collection-runs", tags=["collection runs"])


@sources_router.get("", response_model=list[JobSourceResponse])
async def list_sources(user: CurrentUser, session: SessionDep):
    return await JobService(session).list_sources(user.id)


@sources_router.post("", response_model=JobSourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(payload: JobSourceCreate, user: CurrentUser, session: SessionDep):
    return await JobService(session).create_source(user.id, payload)


@sources_router.get("/{source_id}", response_model=JobSourceResponse)
async def get_source(source_id: UUID, user: CurrentUser, session: SessionDep):
    return source_response(await JobService(session).get_source(source_id, user.id))


@sources_router.patch("/{source_id}", response_model=JobSourceResponse)
async def update_source(source_id: UUID, payload: JobSourcePatch, user: CurrentUser, session: SessionDep):
    return await JobService(session).update_source(source_id, user.id, payload)


@sources_router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: UUID, user: CurrentUser, session: SessionDep):
    await JobService(session).delete_source(source_id, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@sources_router.post("/{source_id}/test")
async def test_source(source_id: UUID, user: CurrentUser, session: SessionDep):
    return await JobService(session).test_source(source_id, user.id)


@sources_router.post("/{source_id}/collect", response_model=CollectionRunResponse)
async def collect_source(source_id: UUID, user: CurrentUser, session: SessionDep):
    return await JobService(session).collect_source(source_id, user.id)


@sources_router.get("/{source_id}/runs", response_model=list[CollectionRunResponse])
async def source_runs(source_id: UUID, user: CurrentUser, session: SessionDep):
    return await JobService(session).runs_for_source(source_id, user.id)


@jobs_router.get("", response_model=JobListResponse)
async def list_jobs(
    user: CurrentUser,
    session: SessionDep,
    search: str | None = None,
    location: str | None = None,
    work_mode: str | None = None,
    source_id: UUID | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
):
    return await JobService(session).list_jobs(user.id, search=search, location=location, work_mode=work_mode,
                                               source_id=source_id, offset=offset, limit=limit)


@jobs_router.post("/import", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def import_job(payload: JobImport, user: CurrentUser, session: SessionDep):
    return await JobService(session).import_job(user, payload)


@jobs_router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: UUID, user: CurrentUser, session: SessionDep):
    return await JobService(session).get_job(job_id, user.id)


@jobs_router.post("/{job_id}/refresh", response_model=JobResponse)
async def refresh_job(job_id: UUID, user: CurrentUser, session: SessionDep):
    service = JobService(session)
    job = await service.get_job(job_id, user.id)
    source = await service.get_source(job["source_id"], user.id)
    if source.source_type in {"MANUAL", "GMAIL_ALERT", "LINKEDIN", "NAUKRI", "INSTAHYRE", "CUTSHORT", "HIRIST", "INDEED", "WELLFOUND", "FOUNDIT"}:
        raise HTTPException(status_code=409, detail="This job source has no configured refresh connector")
    await service.collect_source(job["source_id"], user.id)
    return await service.get_job(job_id, user.id)


@runs_router.get("", response_model=list[CollectionRunResponse])
async def all_runs(user: CurrentUser, session: SessionDep):
    return await JobService(session).all_runs(user.id)
