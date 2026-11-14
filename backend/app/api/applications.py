from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.dependencies import CurrentUser, SessionDep
from app.models.enums import DraftType
from app.schemas.applications import (
    ApplicationCreate, ApplicationStatusPatch, ChecklistUpdate, DraftEdit, FinalApprovalRequest,
    GenerateRequest, JobReviewAction, SubmissionConfirmation,
)
from app.services.applications import ApplicationService, draft_view

reviews_router = APIRouter(prefix="/job-reviews", tags=["job reviews"])
applications_router = APIRouter(prefix="/applications", tags=["applications"])


@reviews_router.get("")
async def list_reviews(user: CurrentUser, session: SessionDep):
    return await ApplicationService(session).list_reviews(user.id)


@reviews_router.post("/{job_id}/approve")
async def approve_job(job_id: UUID, user: CurrentUser, session: SessionDep):
    return await ApplicationService(session).review_job(user.id, job_id, "approve")


@reviews_router.post("/{job_id}/save")
async def save_job(job_id: UUID, user: CurrentUser, session: SessionDep):
    return await ApplicationService(session).review_job(user.id, job_id, "save")


@reviews_router.post("/{job_id}/reject")
async def reject_job(job_id: UUID, payload: JobReviewAction, user: CurrentUser, session: SessionDep):
    return await ApplicationService(session).review_job(user.id, job_id, "reject", payload.reason)


@applications_router.get("/tracking")
async def tracking(user: CurrentUser, session: SessionDep):
    return await ApplicationService(session).tracking(user.id)


@applications_router.get("")
async def list_applications(user: CurrentUser, session: SessionDep):
    return await ApplicationService(session).list_applications(user.id)


@applications_router.post("", status_code=status.HTTP_201_CREATED)
async def create_application(payload: ApplicationCreate, user: CurrentUser, session: SessionDep):
    return await ApplicationService(session).create(user.id, job_id=payload.job_id, resume_version_id=payload.resume_version_id, job_match_id=payload.job_match_id)


@applications_router.get("/{application_id}")
async def get_application(application_id: UUID, user: CurrentUser, session: SessionDep):
    return await ApplicationService(session).get_view(user.id, application_id)


@applications_router.patch("/{application_id}/status")
async def patch_status(application_id: UUID, payload: ApplicationStatusPatch, user: CurrentUser, session: SessionDep):
    return await ApplicationService(session).patch_status(user.id, application_id, payload.status)


@applications_router.post("/{application_id}/generate")
async def generate(application_id: UUID, payload: GenerateRequest, user: CurrentUser, session: SessionDep):
    return await ApplicationService(session).generate(user.id, application_id, payload.draft_types, payload.user_context)


@applications_router.post("/{application_id}/regenerate")
async def regenerate(application_id: UUID, payload: GenerateRequest, user: CurrentUser, session: SessionDep):
    return await ApplicationService(session).generate(user.id, application_id, payload.draft_types, payload.user_context, regenerate=True)


@applications_router.get("/{application_id}/drafts")
async def list_drafts(application_id: UUID, user: CurrentUser, session: SessionDep, draft_type: DraftType | None = Query(default=None)):
    drafts = await ApplicationService(session).list_drafts(user.id, application_id)
    return [draft for draft in drafts if draft_type is None or draft["draft_type"] == draft_type]


@applications_router.get("/{application_id}/drafts/{draft_id}")
async def get_draft(application_id: UUID, draft_id: UUID, user: CurrentUser, session: SessionDep):
    return draft_view(await ApplicationService(session).get_draft(user.id, application_id, draft_id))


@applications_router.patch("/{application_id}/drafts/{draft_id}")
async def edit_draft(application_id: UUID, draft_id: UUID, payload: DraftEdit, user: CurrentUser, session: SessionDep):
    return await ApplicationService(session).edit_draft(user.id, application_id, draft_id, payload.body)


@applications_router.post("/{application_id}/drafts/{draft_id}/approve")
async def approve_draft(application_id: UUID, draft_id: UUID, user: CurrentUser, session: SessionDep):
    return await ApplicationService(session).approve_draft(user.id, application_id, draft_id)


@applications_router.get("/{application_id}/checklist")
async def get_checklist(application_id: UUID, user: CurrentUser, session: SessionDep):
    return await ApplicationService(session).checklist(user.id, application_id)


@applications_router.put("/{application_id}/checklist")
async def put_checklist(application_id: UUID, payload: ChecklistUpdate, user: CurrentUser, session: SessionDep):
    return await ApplicationService(session).update_checklist(user.id, application_id, {key: value.model_dump() for key, value in payload.items.items()})


@applications_router.post("/{application_id}/final-approval")
async def final_approval(application_id: UUID, payload: FinalApprovalRequest, user: CurrentUser, session: SessionDep):
    return await ApplicationService(session).final_approval(user.id, application_id, payload.confirmed)


@applications_router.post("/{application_id}/open-url")
async def open_url(application_id: UUID, user: CurrentUser, session: SessionDep):
    return await ApplicationService(session).open_application_url(user.id, application_id)


@applications_router.post("/{application_id}/confirm-submission")
async def confirm_submission(application_id: UUID, payload: SubmissionConfirmation, user: CurrentUser, session: SessionDep):
    return await ApplicationService(session).confirm_submission(user.id, application_id, payload.submitted, payload.notes)


@applications_router.get("/{application_id}/audit")
async def audit(application_id: UUID, user: CurrentUser, session: SessionDep):
    return await ApplicationService(session).audit(user.id, application_id)
