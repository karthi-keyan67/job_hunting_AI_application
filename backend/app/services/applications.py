from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.core.config import Settings, get_settings
from app.models.applications import Application, ApplicationApproval, ApplicationAuditLog, ApplicationChecklist, ApplicationDraft
from app.models.enums import ApplicationStatus, ApprovalType, DraftStatus, DraftType, ReviewStatus
from app.models.jobs import JobMatch, JobReview
from app.repositories.applications import ApplicationRepository
from app.schemas.applications import CHECKLIST_ITEMS
from app.services.application_generation import GENERATION_PROMPT_VERSION, generate_one
from app.services.matching import match_response

FINAL_DRAFT_TYPES = {DraftType.TAILORED_RESUME, DraftType.COVER_LETTER, DraftType.RECRUITER_MESSAGE, DraftType.APPLICATION_ANSWERS}


def _job_view(job) -> dict:
    return {"id": str(job.id), "title": job.title, "company_name": job.company_name, "location": job.location,
            "work_mode": job.work_mode, "employment_type": job.employment_type, "description": job.description,
            "job_url": job.job_url, "apply_url": job.apply_url, "source_name": job.source.name if job.source else None}


def application_view(application: Application) -> dict:
    return {"id": application.id, "job_id": application.job_id, "resume_version_id": application.resume_version_id,
            "job_match_id": application.job_match_id, "job_review_id": application.job_review_id, "status": application.status,
            "submitted_at": application.submitted_at, "job": _job_view(application.job), "created_at": application.created_at,
            "updated_at": application.updated_at, "notes": application.notes,
            "match_score": float(application.match.overall_score) if application.match else None,
            "resume_version": ({"id": application.resume_version.id, "version_number": application.resume_version.version_number,
                                "title": application.resume_version.resume.title} if application.resume_version else None),
            "approved_documents": [{"id": str(draft.id), "draft_type": draft.draft_type.value, "version_number": draft.version}
                                   for draft in application.drafts if draft.status == DraftStatus.APPROVED],
            "checklist": application.checklist.checks if application.checklist else {}}


def draft_view(draft: ApplicationDraft) -> dict:
    return {"id": draft.id, "application_id": draft.application_id, "draft_type": draft.draft_type,
            "version_number": draft.version, "body": draft.body or draft.content.get("body", ""), "status": draft.status,
            "generated_by": draft.generated_by, "generation_model": draft.generation_model,
            "prompt_version": draft.prompt_version, "evidence": draft.evidence or [], "created_at": draft.created_at}


class ApplicationService:
    def __init__(self, session, settings: Settings | None = None):
        self.session = session
        self.repo = ApplicationRepository(session)
        self.settings = settings or get_settings()

    async def list_reviews(self, user_id: UUID):
        ranked = select(JobMatch.id.label("match_id"), func.row_number().over(partition_by=JobMatch.job_id, order_by=JobMatch.created_at.desc()).label("row_num")).where(JobMatch.user_id == user_id).subquery()
        query = select(JobMatch).join(ranked, ranked.c.match_id == JobMatch.id).where(ranked.c.row_num == 1).order_by(JobMatch.created_at.desc())
        matches = list(await self.session.scalars(query))
        reviews = {review.job_id: review for review in await self.session.scalars(select(JobReview).where(JobReview.user_id == user_id))}
        result = []
        for match in matches:
            job = await self.repo.get_owned_job(user_id, match.job_id)
            if job is None:
                continue
            review = reviews.get(job.id)
            if review is None:
                review = JobReview(user_id=user_id, job_id=job.id, status=ReviewStatus.PENDING_REVIEW, match_id=match.id)
                self.session.add(review)
                await self.session.flush()
                await self.repo.add_review_event(review, user_id, ReviewStatus.PENDING_REVIEW.value)
            events = await self.repo.review_events(review.id)
            result.append({"id": review.id, "job_id": job.id, "status": review.status.value, "rejection_reason": review.rejection_reason,
                           "history": [{"status": event.status, "reason": event.rejection_reason, "created_at": event.created_at} for event in events],
                           "match": match_response(match, job)})
        await self.session.commit()
        return result

    async def review_job(self, user_id: UUID, job_id: UUID, action: str, reason: str | None = None):
        job = await self.repo.get_owned_job(user_id, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        match = await self.repo.latest_match(user_id, job_id)
        if match is None:
            raise HTTPException(status_code=409, detail="Run job matching before reviewing this job")
        targets = {"approve": ReviewStatus.APPROVED_FOR_PREPARATION, "save": ReviewStatus.SAVED, "reject": ReviewStatus.REJECTED}
        status = targets[action]
        review = await self.repo.review(user_id, job_id, lock=True)
        if review is None:
            review = JobReview(user_id=user_id, job_id=job_id, match_id=match.id, status=status)
            self.session.add(review)
            await self.session.flush()
        else:
            review.status = status
            review.match_id = match.id
        review.rejection_reason = reason if status == ReviewStatus.REJECTED else None
        await self.repo.add_review_event(review, user_id, status.value, review.rejection_reason)
        audit_action = {ReviewStatus.APPROVED_FOR_PREPARATION: "JOB_APPROVED_FOR_PREPARATION", ReviewStatus.SAVED: "JOB_SAVED", ReviewStatus.REJECTED: "JOB_REJECTED"}[status]
        await self.repo.audit(None, audit_action, user_id, {"job_id": str(job_id), "review_status": status.value}, job_review_id=review.id)
        await self.session.commit()
        return {"id": review.id, "job_id": job_id, "status": status.value, "rejection_reason": review.rejection_reason}

    async def create(self, user_id: UUID, *, job_id: UUID, resume_version_id: UUID, job_match_id: UUID):
        job = await self.repo.get_owned_job(user_id, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        review = await self.repo.review(user_id, job_id)
        if review is None or review.status != ReviewStatus.APPROVED_FOR_PREPARATION:
            raise HTTPException(status_code=409, detail="Approve this job for preparation before creating an application")
        version = await self.repo.owned_resume_version(user_id, resume_version_id)
        if version is None:
            raise HTTPException(status_code=404, detail="Resume version not found")
        match = await self.repo.owned_match(user_id, job_id, job_match_id)
        if match is None:
            raise HTTPException(status_code=404, detail="Matching result not found")
        application = Application(user_id=user_id, job_id=job_id, resume_version_id=resume_version_id, job_match_id=job_match_id, job_review_id=review.id, status=ApplicationStatus.PREPARING)
        self.session.add(application)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise HTTPException(status_code=409, detail="An application already exists for this job") from exc
        checklist = ApplicationChecklist(application_id=application.id, checks={})
        self.session.add(checklist)
        await self.repo.audit(application.id, "APPLICATION_CREATED", user_id, {"job_id": str(job_id), "resume_version_id": str(resume_version_id), "job_match_id": str(job_match_id)})
        await self.session.commit()
        return application_view(await self.repo.application(user_id, application.id))

    async def list_applications(self, user_id: UUID):
        return [application_view(item) for item in await self.repo.applications(user_id)]

    async def get(self, user_id: UUID, application_id: UUID):
        application = await self.repo.application(user_id, application_id)
        if application is None:
            raise HTTPException(status_code=404, detail="Application not found")
        return application

    async def get_view(self, user_id: UUID, application_id: UUID):
        return application_view(await self.get(user_id, application_id))

    async def patch_status(self, user_id: UUID, application_id: UUID, status: ApplicationStatus):
        application = await self.repo.application(user_id, application_id, lock=True)
        if application is None:
            raise HTTPException(status_code=404, detail="Application not found")
        if status in {ApplicationStatus.APPLIED, ApplicationStatus.READY_TO_APPLY}:
            raise HTTPException(status_code=409, detail="Use the final approval or explicit submission confirmation action for this status")
        allowed = {
            ApplicationStatus.SAVED: {ApplicationStatus.PREPARING, ApplicationStatus.ON_HOLD, ApplicationStatus.WITHDRAWN},
            ApplicationStatus.PREPARING: {ApplicationStatus.READY_FOR_REVIEW, ApplicationStatus.SAVED, ApplicationStatus.ON_HOLD, ApplicationStatus.WITHDRAWN},
            ApplicationStatus.READY_FOR_REVIEW: {ApplicationStatus.PREPARING, ApplicationStatus.ON_HOLD, ApplicationStatus.WITHDRAWN},
            ApplicationStatus.READY_TO_APPLY: {ApplicationStatus.PREPARING, ApplicationStatus.ON_HOLD, ApplicationStatus.WITHDRAWN},
            ApplicationStatus.APPLIED: {ApplicationStatus.ASSESSMENT, ApplicationStatus.INTERVIEW, ApplicationStatus.ON_HOLD, ApplicationStatus.OFFER, ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN, ApplicationStatus.ACCEPTED},
            ApplicationStatus.ASSESSMENT: {ApplicationStatus.INTERVIEW, ApplicationStatus.ON_HOLD, ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN},
            ApplicationStatus.INTERVIEW: {ApplicationStatus.OFFER, ApplicationStatus.ON_HOLD, ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN, ApplicationStatus.ACCEPTED},
            ApplicationStatus.ON_HOLD: {ApplicationStatus.PREPARING, ApplicationStatus.READY_FOR_REVIEW, ApplicationStatus.ASSESSMENT, ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER, ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN},
            ApplicationStatus.OFFER: {ApplicationStatus.ACCEPTED, ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN, ApplicationStatus.ON_HOLD},
        }
        if status not in allowed.get(application.status, {ApplicationStatus.ON_HOLD, ApplicationStatus.WITHDRAWN}):
            raise HTTPException(status_code=409, detail=f"Invalid application status transition: {application.status.value} to {status.value}")
        prior = application.status.value
        application.status = status
        if prior == ApplicationStatus.READY_TO_APPLY.value:
            final = await self.session.scalar(select(ApplicationApproval).where(ApplicationApproval.application_id == application_id, ApplicationApproval.approval_type == ApprovalType.FINAL, ApplicationApproval.approved.is_(True)).with_for_update())
            if final:
                final.approved = False
                final.approved_at = None
                await self.repo.audit(application.id, "APPROVAL_INVALIDATED", user_id, {"reason": "application_status_changed"})
        await self.repo.audit(application.id, "APPLICATION_STATUS_UPDATED", user_id, {"from": prior, "to": status.value})
        await self.session.commit()
        await self.session.refresh(application, attribute_names=["updated_at"])
        return application_view(application)

    async def generate(self, user_id: UUID, application_id: UUID, draft_types: list[DraftType], user_context: dict[str, str], *, regenerate: bool = False):
        application = await self.repo.application(user_id, application_id, lock=True)
        if application is None:
            raise HTTPException(status_code=404, detail="Application not found")
        if application.status in {ApplicationStatus.APPLIED, ApplicationStatus.ACCEPTED, ApplicationStatus.WITHDRAWN}:
            raise HTTPException(status_code=409, detail="This application cannot be edited")
        if not self.settings.openai_api_key:
            raise HTTPException(status_code=503, detail="AI application preparation is not configured")
        await self.session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"application-generation:{user_id}"})
        count = await self.repo.daily_generation_count(user_id)
        if count + len(draft_types) > self.settings.application_generation_daily_limit:
            raise HTTPException(status_code=429, detail="Daily AI draft generation limit reached")
        version = await self.repo.owned_resume_version(user_id, application.resume_version_id)
        if version is None:
            raise HTTPException(status_code=409, detail="The selected resume version is unavailable")
        job = await self.repo.get_owned_job(user_id, application.job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        required_skills = [skill.skill_name for skill in job.skills if skill.skill_type == "REQUIRED" or skill.is_required]
        preferred_skills = [skill.skill_name for skill in job.skills if skill.skill_type == "PREFERRED" or not skill.is_required]
        job_data = {"title": job.title, "company_name": job.company_name, "description": job.description, "location": job.location,
                    "work_mode": job.work_mode, "employment_type": job.employment_type, "required_skills": required_skills, "preferred_skills": preferred_skills}
        parsed = version.parsed_data or {}
        permitted_sections = ("skills", "job_titles", "experience", "projects", "education", "certifications", "experience_months")
        resume_data = {key: parsed[key] for key in permitted_sections if parsed.get(key) not in (None, [], "")}
        if not resume_data and version.parsed_text:
            # Raw parse is intentionally not sent because contact information and unsupported facts are difficult to filter reliably.
            resume_data = {"available_sections": [], "text_available": True}
        created = []
        try:
            for draft_type in dict.fromkeys(draft_types):
                body, evidence = await generate_one(self.settings, draft_type=draft_type.value, resume_data=resume_data,
                                                    parsed_text=version.parsed_text, job=job_data, user_context=user_context)
                if draft_type == DraftType.APPLICATION_ANSWERS:
                    body += "\n\n### Details to confirm\n"
                    for label, key in (("Current salary", "current_salary"), ("Expected salary", "expected_salary"), ("Notice period", "notice_period"),
                                       ("Availability", "availability"), ("Work authorization", "work_authorization"), ("Relocation willingness", "relocation_willingness")):
                        value = user_context.get(key, "").strip()
                        body += f"- {label}: {value if value else '[USER INPUT REQUIRED]'}\n"
                current = await self.repo.drafts(application.id, draft_type)
                for old in current:
                    if old.status != DraftStatus.SUPERSEDED:
                        old.status = DraftStatus.SUPERSEDED
                draft = ApplicationDraft(application_id=application.id, draft_type=draft_type, version=await self.repo.next_draft_version(application.id, draft_type),
                                         body=body, content={"body": body}, evidence=evidence, status=DraftStatus.GENERATED,
                                         generated_by="AI", generation_model=self.settings.openai_model, prompt_version=GENERATION_PROMPT_VERSION)
                self.session.add(draft)
                await self.session.flush()
                await self.repo.audit(application.id, "DRAFT_GENERATED", user_id, {"draft_id": str(draft.id), "draft_type": draft_type.value, "version": draft.version, "regeneration": regenerate})
                created.append(draft)
            self._invalidate_approvals(application, set(draft_types))
            application.status = ApplicationStatus.READY_FOR_REVIEW
            await self.session.commit()
        except HTTPException:
            raise
        except Exception as exc:
            await self.session.rollback()
            raise HTTPException(status_code=502, detail="Application draft generation failed; no draft was saved") from exc
        return [draft_view(draft) for draft in created]

    async def list_drafts(self, user_id: UUID, application_id: UUID):
        await self.get(user_id, application_id)
        return [draft_view(item) for item in await self.repo.drafts(application_id)]

    async def get_draft(self, user_id: UUID, application_id: UUID, draft_id: UUID):
        await self.get(user_id, application_id)
        draft = await self.session.scalar(select(ApplicationDraft).where(ApplicationDraft.id == draft_id, ApplicationDraft.application_id == application_id))
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft not found")
        return draft

    def _invalidate_approvals(self, application: Application, draft_types: set[DraftType] | None = None):
        approval_map = {DraftType.TAILORED_RESUME: ApprovalType.RESUME, DraftType.COVER_LETTER: ApprovalType.COVER_LETTER, DraftType.APPLICATION_ANSWERS: ApprovalType.ANSWERS}
        invalid_types = {approval_map[item] for item in (draft_types or set()) if item in approval_map}
        for approval in application.approvals:
            if approval.approved and (approval.approval_type == ApprovalType.FINAL or approval.approval_type in invalid_types):
                approval.approved = False
                approval.approved_at = None

    async def edit_draft(self, user_id: UUID, application_id: UUID, draft_id: UUID, body: str):
        application = await self.repo.application(user_id, application_id, lock=True)
        if application is None:
            raise HTTPException(status_code=404, detail="Application not found")
        old = await self.session.scalar(select(ApplicationDraft).where(ApplicationDraft.id == draft_id, ApplicationDraft.application_id == application_id).with_for_update())
        if old is None:
            raise HTTPException(status_code=404, detail="Draft not found")
        if application.status in {ApplicationStatus.APPLIED, ApplicationStatus.ACCEPTED, ApplicationStatus.WITHDRAWN}:
            raise HTTPException(status_code=409, detail="This application cannot be edited")
        old_status = old.status.value
        if old.status != DraftStatus.SUPERSEDED:
            old.status = DraftStatus.SUPERSEDED
        draft = ApplicationDraft(application_id=application_id, draft_type=old.draft_type, version=await self.repo.next_draft_version(application_id, old.draft_type),
                                 body=body, content={"body": body}, evidence=old.evidence or [], status=DraftStatus.EDITED, generated_by="USER",
                                 generation_model=old.generation_model, prompt_version=old.prompt_version)
        self.session.add(draft)
        self._invalidate_approvals(application, {old.draft_type})
        application.status = ApplicationStatus.READY_FOR_REVIEW
        await self.session.flush()
        await self.repo.audit(application_id, "DRAFT_EDITED", user_id, {"draft_id": str(draft.id), "superseded_draft_id": str(old.id), "prior_status": old_status})
        await self.repo.audit(application_id, "APPROVAL_INVALIDATED", user_id, {"reason": "draft_edited", "draft_type": old.draft_type.value})
        await self.session.commit()
        return draft_view(draft)

    async def approve_draft(self, user_id: UUID, application_id: UUID, draft_id: UUID):
        application = await self.repo.application(user_id, application_id, lock=True)
        if application is None:
            raise HTTPException(status_code=404, detail="Application not found")
        draft = await self.session.scalar(select(ApplicationDraft).where(ApplicationDraft.id == draft_id, ApplicationDraft.application_id == application_id).with_for_update())
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft not found")
        if draft.status == DraftStatus.SUPERSEDED:
            raise HTTPException(status_code=409, detail="Superseded draft versions cannot be approved")
        if draft.status == DraftStatus.APPROVED:
            return draft_view(draft)
        draft.status = DraftStatus.APPROVED
        approval_type = {DraftType.TAILORED_RESUME: ApprovalType.RESUME, DraftType.COVER_LETTER: ApprovalType.COVER_LETTER,
                         DraftType.APPLICATION_ANSWERS: ApprovalType.ANSWERS}.get(draft.draft_type)
        if approval_type:
            approval = await self.session.scalar(select(ApplicationApproval).where(ApplicationApproval.application_id == application_id, ApplicationApproval.approval_type == approval_type).with_for_update())
            if approval is None:
                approval = ApplicationApproval(application_id=application_id, approval_type=approval_type)
                self.session.add(approval)
            approval.approved = True
            approval.approved_at = datetime.now(UTC)
            approval.approver_user_id = user_id
            approval.draft_version_ids = [str(draft.id)]
        await self.repo.audit(application_id, "DRAFT_APPROVED", user_id, {"draft_id": str(draft.id), "draft_type": draft.draft_type.value, "version": draft.version})
        await self.session.commit()
        return draft_view(draft)

    async def checklist(self, user_id: UUID, application_id: UUID):
        application = await self.get(user_id, application_id)
        if application.checklist is None:
            checklist = ApplicationChecklist(application_id=application.id, checks={})
            self.session.add(checklist)
            await self.session.commit()
            checks = {}
        else:
            checks = application.checklist.checks or {}
        return {"items": checks, "required_items": list(CHECKLIST_ITEMS)}

    async def update_checklist(self, user_id: UUID, application_id: UUID, items: dict):
        application = await self.repo.application(user_id, application_id, lock=True)
        if application is None:
            raise HTTPException(status_code=404, detail="Application not found")
        unknown = set(items) - set(CHECKLIST_ITEMS)
        if unknown:
            raise HTTPException(status_code=422, detail=f"Unknown checklist items: {', '.join(sorted(unknown))}")
        for key, value in items.items():
            if value.get("completed") and value.get("not_applicable_reason"):
                raise HTTPException(status_code=422, detail="A completed checklist item cannot also be not applicable")
            if value.get("not_applicable_reason") and len(value["not_applicable_reason"].strip()) < 5:
                raise HTTPException(status_code=422, detail="Not-applicable items require an explanatory reason")
        if application.checklist is None:
            application.checklist = ApplicationChecklist(checks={})
        application.checklist.checks = {**(application.checklist.checks or {}), **{key: value for key, value in items.items()}}
        await self.repo.audit(application_id, "CHECKLIST_UPDATED", user_id, {"changed_items": sorted(items.keys())})
        self._invalidate_approvals(application)
        if application.status == ApplicationStatus.READY_TO_APPLY:
            application.status = ApplicationStatus.READY_FOR_REVIEW
        await self.session.commit()
        return {"items": application.checklist.checks, "required_items": list(CHECKLIST_ITEMS)}

    async def final_approval(self, user_id: UUID, application_id: UUID, confirmed: bool):
        application = await self.repo.application(user_id, application_id, lock=True)
        if application is None:
            raise HTTPException(status_code=404, detail="Application not found")
        if not confirmed:
            raise HTTPException(status_code=422, detail="Explicit final approval is required")
        apply_parts = urlsplit(application.job.apply_url or "")
        if apply_parts.scheme != "https" or not apply_parts.hostname or apply_parts.username or apply_parts.password:
            raise HTTPException(status_code=409, detail="A verified HTTPS application URL is required before final approval")
        checks = application.checklist.checks if application.checklist else {}
        missing = [key for key in CHECKLIST_ITEMS if not (checks.get(key, {}).get("completed") or (checks.get(key, {}).get("not_applicable_reason") or "").strip())]
        drafts = await self.repo.drafts(application.id)
        approved = {draft.draft_type: draft for draft in drafts if draft.status == DraftStatus.APPROVED}
        latest = {}
        for draft in drafts:
            if draft.draft_type not in latest or draft.version > latest[draft.draft_type].version:
                latest[draft.draft_type] = draft
        for draft_type, draft in latest.items():
            if draft.status != DraftStatus.APPROVED and not (draft_type == DraftType.COVER_LETTER and (checks.get("cover_letter_reviewed", {}).get("not_applicable_reason") or "").strip()):
                missing.append(f"approved_latest_{draft_type.value.lower()}")
        approval_types = {DraftType.TAILORED_RESUME: ApprovalType.RESUME, DraftType.COVER_LETTER: ApprovalType.COVER_LETTER, DraftType.APPLICATION_ANSWERS: ApprovalType.ANSWERS}
        for kind, approval_type in approval_types.items():
            if kind in approved:
                row = await self.session.scalar(select(ApplicationApproval).where(ApplicationApproval.application_id == application_id,
                                                                                   ApplicationApproval.approval_type == approval_type,
                                                                                   ApplicationApproval.approved.is_(True)))
                if row is None or str(approved[kind].id) not in (row.draft_version_ids or []):
                    approved.pop(kind, None)
        for kind, checklist_key in ((DraftType.TAILORED_RESUME, "tailored_resume_reviewed"), (DraftType.APPLICATION_ANSWERS, "application_answers_reviewed")):
            if kind not in approved:
                missing.append(f"approved_{kind.value.lower()}")
        if DraftType.COVER_LETTER not in approved and not (checks.get("cover_letter_reviewed", {}).get("not_applicable_reason") or "").strip():
            missing.append("approved_cover_letter_or_not_required")
        if missing:
            raise HTTPException(status_code=409, detail={"message": "Complete the checklist and approve the required draft versions", "missing": missing})
        if application.status in {ApplicationStatus.APPLIED, ApplicationStatus.ACCEPTED, ApplicationStatus.WITHDRAWN}:
            raise HTTPException(status_code=409, detail="This application cannot receive final approval")
        review = await self.repo.review(user_id, application.job_id)
        if review is None or review.status != ReviewStatus.APPROVED_FOR_PREPARATION:
            raise HTTPException(status_code=409, detail="The job must remain approved for application preparation")
        snapshot_ids = [str(item.id) for item in sorted(approved.values(), key=lambda draft: draft.draft_type.value)]
        approval = await self.session.scalar(select(ApplicationApproval).where(ApplicationApproval.application_id == application_id, ApplicationApproval.approval_type == ApprovalType.FINAL).with_for_update())
        if approval is None:
            approval = ApplicationApproval(application_id=application.id, approval_type=ApprovalType.FINAL)
            self.session.add(approval)
        approval.approved = True
        approval.approved_at = datetime.now(UTC)
        approval.approver_user_id = user_id
        approval.draft_version_ids = snapshot_ids
        approval.checklist_snapshot = checks
        application.status = ApplicationStatus.READY_TO_APPLY
        checklist_summary = {key: {"completed": bool(value.get("completed")), "not_applicable": bool((value.get("not_applicable_reason") or "").strip())} for key, value in checks.items()}
        await self.repo.audit(application_id, "FINAL_APPROVAL_GRANTED", user_id, {"draft_version_ids": snapshot_ids, "checklist_summary": checklist_summary})
        await self.session.commit()
        await self.session.refresh(application, attribute_names=["updated_at"])
        return {"application": application_view(application), "approved_draft_ids": snapshot_ids, "approved_at": approval.approved_at}

    async def open_application_url(self, user_id: UUID, application_id: UUID):
        application = await self.get(user_id, application_id)
        if application.status != ApplicationStatus.READY_TO_APPLY:
            raise HTTPException(status_code=409, detail="Complete final approval before opening the application site")
        url = application.job.apply_url
        parts = urlsplit(url or "")
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise HTTPException(status_code=422, detail="A verified HTTPS application URL is required")
        await self.repo.audit(application.id, "APPLICATION_URL_OPENED", user_id, {"hostname": parts.hostname})
        await self.session.commit()
        return {"url": url, "reminder": "Review the destination website, then fill and submit the application manually."}

    async def confirm_submission(self, user_id: UUID, application_id: UUID, submitted: bool, notes: str | None):
        application = await self.repo.application(user_id, application_id, lock=True)
        if application is None:
            raise HTTPException(status_code=404, detail="Application not found")
        if not submitted:
            raise HTTPException(status_code=422, detail="Confirm only after you manually submit the application")
        if application.status != ApplicationStatus.READY_TO_APPLY:
            raise HTTPException(status_code=409, detail="Application must be finally approved before submission confirmation")
        final = await self.session.scalar(select(ApplicationApproval).where(ApplicationApproval.application_id == application_id, ApplicationApproval.approval_type == ApprovalType.FINAL, ApplicationApproval.approved.is_(True)))
        if final is None:
            raise HTTPException(status_code=409, detail="Final human approval is required")
        application.status = ApplicationStatus.APPLIED
        application.submitted_at = datetime.now(UTC)
        await self.repo.audit(application_id, "APPLICATION_MARKED_APPLIED", user_id, {"confirmed": True, "confirmed_at": application.submitted_at.isoformat(), "note_provided": bool(notes)})
        await self.session.commit()
        await self.session.refresh(application, attribute_names=["updated_at"])
        return application_view(application)

    async def audit(self, user_id: UUID, application_id: UUID):
        application = await self.get(user_id, application_id)
        events = await self.repo.audit_events(application.id)
        return [{"id": event.id, "action": event.action, "occurred_at": event.occurred_at, "details": event.details} for event in events]

    async def tracking(self, user_id: UUID):
        result = []
        for application in await self.repo.applications(user_id):
            result.append({"application": application_view(application), "timeline": await self.audit(user_id, application.id)})
        return result
