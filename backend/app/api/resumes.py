from uuid import UUID

from fastapi import APIRouter, File, Form, Response, UploadFile, status

from app.api.dependencies import CurrentUser, SessionDep
from app.schemas.resume import ResumeResponse
from app.services.resume import ResumeService

router = APIRouter(prefix="/resumes", tags=["resumes"])


@router.post("", response_model=ResumeResponse, status_code=status.HTTP_201_CREATED)
async def upload_resume(user: CurrentUser, session: SessionDep, file: UploadFile = File(...), title: str | None = Form(None)):
    return await ResumeService(session).create(user, file, title)


@router.get("", response_model=list[ResumeResponse])
async def list_resumes(user: CurrentUser, session: SessionDep):
    return await ResumeService(session).list(user.id)


@router.get("/{resume_id}", response_model=ResumeResponse)
async def get_resume(resume_id: UUID, user: CurrentUser, session: SessionDep):
    return await ResumeService(session).get(resume_id, user.id)


@router.post("/{resume_id}/versions", response_model=ResumeResponse, status_code=status.HTTP_201_CREATED)
async def upload_version(resume_id: UUID, user: CurrentUser, session: SessionDep, file: UploadFile = File(...), force_new_version: bool = Form(False)):
    return await ResumeService(session).add_version(user.id, resume_id, file, force_new_version)


@router.get("/{resume_id}/versions/{version_id}/download")
async def download_version(resume_id: UUID, version_id: UUID, user: CurrentUser, session: SessionDep):
    return await ResumeService(session).download(user.id, resume_id, version_id)


@router.post("/{resume_id}/default", response_model=ResumeResponse)
async def make_default(resume_id: UUID, user: CurrentUser, session: SessionDep):
    return await ResumeService(session).set_default(resume_id, user.id)


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(resume_id: UUID, user: CurrentUser, session: SessionDep):
    await ResumeService(session).delete(user.id, resume_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{resume_id}/versions/{version_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_version(resume_id: UUID, version_id: UUID, user: CurrentUser, session: SessionDep):
    await ResumeService(session).delete_version(user.id, resume_id, version_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
