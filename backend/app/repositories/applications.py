from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.account import ResumeVersion
from app.models.applications import Application, ApplicationAuditLog, ApplicationDraft, ApplicationChecklist
from app.models.enums import DraftType
from app.models.jobs import Job, JobMatch, JobReview, JobReviewEvent, JobSource


class ApplicationRepository:
    def __init__(self, session):
        self.session = session

    async def get_owned_job(self, user_id: UUID, job_id: UUID):
        return await self.session.scalar(select(Job).join(JobSource).where(Job.id == job_id, JobSource.user_id == user_id).options(selectinload(Job.skills), selectinload(Job.source)))

    async def latest_match(self, user_id: UUID, job_id: UUID):
        return await self.session.scalar(select(JobMatch).where(JobMatch.user_id == user_id, JobMatch.job_id == job_id).order_by(JobMatch.created_at.desc()).limit(1))

    async def owned_match(self, user_id: UUID, job_id: UUID, match_id: UUID):
        return await self.session.scalar(select(JobMatch).where(JobMatch.id == match_id, JobMatch.user_id == user_id, JobMatch.job_id == job_id))

    async def owned_resume_version(self, user_id: UUID, version_id: UUID):
        return await self.session.scalar(select(ResumeVersion).join(ResumeVersion.resume).where(ResumeVersion.id == version_id, ResumeVersion.resume.has(user_id=user_id)))

    async def review(self, user_id: UUID, job_id: UUID, *, lock: bool = False):
        query = select(JobReview).where(JobReview.user_id == user_id, JobReview.job_id == job_id).options(selectinload(JobReview.history))
        if lock:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def application(self, user_id: UUID, application_id: UUID, *, lock: bool = False):
        query = select(Application).where(Application.id == application_id, Application.user_id == user_id).options(
            selectinload(Application.job).selectinload(Job.source), selectinload(Application.drafts),
            selectinload(Application.approvals), selectinload(Application.checklist), selectinload(Application.match),
            selectinload(Application.resume_version).selectinload(ResumeVersion.resume),
        )
        if lock:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def applications(self, user_id: UUID):
        rows = await self.session.scalars(select(Application).where(Application.user_id == user_id).options(
            selectinload(Application.job).selectinload(Job.source), selectinload(Application.match),
            selectinload(Application.resume_version).selectinload(ResumeVersion.resume),
            selectinload(Application.drafts), selectinload(Application.checklist),
        ).order_by(Application.updated_at.desc()))
        return list(rows)

    async def drafts(self, application_id: UUID, draft_type: DraftType | None = None):
        query = select(ApplicationDraft).where(ApplicationDraft.application_id == application_id).order_by(ApplicationDraft.draft_type, ApplicationDraft.version)
        if draft_type:
            query = query.where(ApplicationDraft.draft_type == draft_type)
        return list(await self.session.scalars(query))

    async def next_draft_version(self, application_id: UUID, draft_type: DraftType) -> int:
        current = await self.session.scalar(select(func.max(ApplicationDraft.version)).where(ApplicationDraft.application_id == application_id, ApplicationDraft.draft_type == draft_type))
        return int(current or 0) + 1

    async def audit(self, application_id: UUID | None, action: str, user_id: UUID, details: dict | None = None, *, job_review_id: UUID | None = None):
        self.session.add(ApplicationAuditLog(application_id=application_id, job_review_id=job_review_id, actor_user_id=user_id, action=action, details=details or {}))

    async def add_review_event(self, review: JobReview, user_id: UUID, status: str, reason: str | None = None):
        event = JobReviewEvent(job_review_id=review.id, user_id=user_id, status=status, rejection_reason=reason)
        self.session.add(event)

    async def review_events(self, review_id: UUID):
        return list(await self.session.scalars(select(JobReviewEvent).where(JobReviewEvent.job_review_id == review_id).order_by(JobReviewEvent.created_at, JobReviewEvent.id)))

    async def audit_events(self, application_id: UUID):
        rows = await self.session.scalars(select(ApplicationAuditLog).where(ApplicationAuditLog.application_id == application_id).order_by(ApplicationAuditLog.occurred_at, ApplicationAuditLog.id))
        return list(rows)

    async def daily_generation_count(self, user_id: UUID):
        from datetime import UTC, datetime, timedelta
        return await self.session.scalar(select(func.count(ApplicationDraft.id)).join(Application).where(Application.user_id == user_id, ApplicationDraft.generated_by == "AI", ApplicationDraft.created_at >= datetime.now(UTC) - timedelta(days=1))) or 0
