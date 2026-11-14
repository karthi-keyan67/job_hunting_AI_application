from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.enums import ApplicationStatus, DraftStatus, DraftType


class JobReviewAction(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class JobReviewItem(BaseModel):
    id: UUID
    job_id: UUID
    status: str
    rejection_reason: str | None
    history: list[dict]
    match: dict


class ApplicationCreate(BaseModel):
    job_id: UUID
    resume_version_id: UUID
    job_match_id: UUID


class ApplicationStatusPatch(BaseModel):
    status: ApplicationStatus


class ApplicationView(BaseModel):
    id: UUID
    job_id: UUID
    resume_version_id: UUID | None
    job_match_id: UUID | None
    job_review_id: UUID | None
    status: ApplicationStatus
    submitted_at: datetime | None
    job: dict
    created_at: datetime
    updated_at: datetime


class GenerateRequest(BaseModel):
    draft_types: list[DraftType] = Field(default_factory=lambda: list(DraftType), min_length=1, max_length=4)
    user_context: dict[str, str] = Field(default_factory=dict)

    @field_validator("user_context")
    @classmethod
    def bound_context(cls, value: dict[str, str]):
        if len(value) > 30 or any(len(key) > 80 or len(item) > 1000 for key, item in value.items()):
            raise ValueError("User context is too large")
        return value


class DraftEdit(BaseModel):
    body: str = Field(min_length=1, max_length=50000)


class DraftView(BaseModel):
    id: UUID
    application_id: UUID
    draft_type: DraftType
    version_number: int
    body: str
    status: DraftStatus
    generated_by: str
    generation_model: str | None
    prompt_version: str
    evidence: list
    created_at: datetime


CHECKLIST_ITEMS = (
    "job_details_verified", "company_verified", "application_url_verified", "selected_resume_reviewed",
    "tailored_resume_reviewed", "cover_letter_reviewed", "application_answers_reviewed",
    "expected_salary_confirmed", "notice_period_confirmed", "personal_information_confirmed",
)


class ChecklistItem(BaseModel):
    completed: bool = False
    not_applicable_reason: str | None = Field(default=None, max_length=1000)


class ChecklistUpdate(BaseModel):
    items: dict[str, ChecklistItem]


class ChecklistView(BaseModel):
    items: dict[str, dict]
    required_items: list[str]


class FinalApprovalRequest(BaseModel):
    confirmed: bool


class SubmissionConfirmation(BaseModel):
    submitted: bool
    notes: str | None = Field(default=None, max_length=2000)


class AuditEvent(BaseModel):
    id: UUID
    action: str
    occurred_at: datetime
    details: dict


class ApplicationTracking(BaseModel):
    application: ApplicationView
    timeline: list[AuditEvent]

