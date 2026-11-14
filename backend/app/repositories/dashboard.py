from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, distinct, func, or_, select
from sqlalchemy.orm import selectinload

from app.models.account import ResumeVersion
from app.models.applications import Application, ApplicationAuditLog, ApplicationEvent
from app.models.enums import ApplicationStatus, FollowUpStatus, InterviewStatus, ReviewStatus
from app.models.jobs import Job, JobMatch, JobReview, JobReviewEvent, JobSource
from app.models.tracking import FollowUp, Interview


def _bounds(start_date: date | None, end_date: date | None):
    timezone = ZoneInfo("Asia/Kolkata")
    start = datetime.combine(start_date, time.min, tzinfo=timezone).astimezone(UTC) if start_date else None
    end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone).astimezone(UTC) if end_date else None
    return start, end


class DashboardRepository:
    def __init__(self, session):
        self.session = session

    async def summary(self, user_id: UUID, start_date: date | None, end_date: date | None):
        start, end = _bounds(start_date, end_date)
        owned_jobs = select(Job.id).join(JobSource, Job.source_id == JobSource.id).where(JobSource.user_id == user_id)
        total_jobs = await self.session.scalar(select(func.count()).select_from(Job).where(Job.id.in_(owned_jobs))) or 0
        jobs_query = select(func.count(distinct(Job.id))).join(JobSource).where(JobSource.user_id == user_id)
        if start:
            jobs_query = jobs_query.where(Job.first_seen_at >= start)
        if end:
            jobs_query = jobs_query.where(Job.first_seen_at < end)
        new_jobs = await self.session.scalar(jobs_query) or 0

        ranked_matches = select(JobMatch.id.label("match_id"), func.row_number().over(partition_by=JobMatch.job_id, order_by=(JobMatch.created_at.desc(), JobMatch.id.desc())).label("row_num")).where(JobMatch.user_id == user_id).subquery()
        ai_recommendation = JobMatch.ai_analysis["recommendation"].as_string()
        is_strong = and_(JobMatch.eligibility_status != "MISMATCH", or_(ai_recommendation == "APPLY", (ai_recommendation.is_(None) | (ai_recommendation == "")) & (JobMatch.overall_score >= 75)))
        match_query = select(func.count(JobMatch.id)).join(ranked_matches, ranked_matches.c.match_id == JobMatch.id).where(JobMatch.user_id == user_id, ranked_matches.c.row_num == 1, is_strong)
        if start:
            match_query = match_query.where(JobMatch.created_at >= start)
        if end:
            match_query = match_query.where(JobMatch.created_at < end)
        strong_matches = await self.session.scalar(match_query) or 0

        latest_review_jobs = select(JobMatch.job_id.label("job_id"), func.row_number().over(partition_by=JobMatch.job_id, order_by=(JobMatch.created_at.desc(), JobMatch.id.desc())).label("row_num")).where(JobMatch.user_id == user_id).subquery()
        pending_query = select(func.count(distinct(latest_review_jobs.c.job_id))).outerjoin(JobReview, (JobReview.job_id == latest_review_jobs.c.job_id) & (JobReview.user_id == user_id)).where(latest_review_jobs.c.row_num == 1, or_(JobReview.id.is_(None), JobReview.status.in_([ReviewStatus.PENDING, ReviewStatus.PENDING_REVIEW])))
        pending = await self.session.scalar(pending_query) or 0
        approved = await self.session.scalar(select(func.count(JobReview.id)).where(JobReview.user_id == user_id, JobReview.status.in_([ReviewStatus.APPROVED, ReviewStatus.APPROVED_FOR_PREPARATION]))) or 0
        apps = select(Application.status, func.count(Application.id)).where(Application.user_id == user_id)
        if start:
            apps = apps.where(Application.created_at >= start)
        if end:
            apps = apps.where(Application.created_at < end)
        statuses = {status.value: count for status, count in (await self.session.execute(apps.group_by(Application.status))).all()}
        return {
            "total_jobs_discovered": int(total_jobs), "new_jobs": int(new_jobs), "strong_matches": int(strong_matches),
            "jobs_pending_review": int(pending), "jobs_approved_for_preparation": int(approved),
            "applications_in_preparation": int(statuses.get(ApplicationStatus.PREPARING.value, 0) + statuses.get(ApplicationStatus.READY_FOR_REVIEW.value, 0)),
            "ready_to_apply_applications": int(statuses.get(ApplicationStatus.READY_TO_APPLY.value, 0)),
            "submitted_applications": int(statuses.get(ApplicationStatus.APPLIED.value, 0)),
            "interviews": int(statuses.get(ApplicationStatus.INTERVIEW.value, 0)),
            "offers": int(statuses.get(ApplicationStatus.OFFER.value, 0)),
            "rejected_applications": int(statuses.get(ApplicationStatus.REJECTED.value, 0)),
            "date_range": {"start_date": start_date, "end_date": end_date},
        }

    async def recent_matches(self, user_id: UUID, limit: int = 8):
        rows = (await self.session.execute(select(JobMatch, Job).join(Job, Job.id == JobMatch.job_id).where(JobMatch.user_id == user_id).options(selectinload(Job.source)).order_by(JobMatch.created_at.desc()).limit(limit))).all()
        return [{"id": match.id, "job_id": job.id, "title": job.title, "company_name": job.company_name, "overall_score": match.overall_score, "confidence": match.confidence, "created_at": match.created_at, "location": job.location, "work_mode": job.work_mode} for match, job in rows]

    async def recent_activity(self, user_id: UUID, limit: int = 20):
        query = select(ApplicationAuditLog, Application, Job, JobReview).outerjoin(Application, Application.id == ApplicationAuditLog.application_id).outerjoin(Job, Job.id == Application.job_id).outerjoin(JobReview, JobReview.id == ApplicationAuditLog.job_review_id).where(or_(Application.user_id == user_id, JobReview.user_id == user_id)).order_by(ApplicationAuditLog.occurred_at.desc(), ApplicationAuditLog.id.desc()).limit(limit)
        rows = (await self.session.execute(query)).all()
        return [{"id": log.id, "action": log.action, "occurred_at": log.occurred_at, "application_id": log.application_id, "job_id": application.job_id if application else review.job_id, "job_title": job.title if job else None, "company_name": job.company_name if job else None, "details": log.details} for log, application, job, review in rows]

    async def pipeline(self, user_id: UUID, *, search: str | None, status: ApplicationStatus | None, date_from: date | None, date_to: date | None, location: str | None, work_mode: str | None, sort_by: str, offset: int, limit: int):
        query = select(Application).join(Job, Job.id == Application.job_id).where(Application.user_id == user_id).options(
            selectinload(Application.job).selectinload(Job.source), selectinload(Application.match),
            selectinload(Application.resume_version).selectinload(ResumeVersion.resume),
            selectinload(Application.drafts), selectinload(Application.checklist),
        )
        if search:
            term = f"%{search.strip()}%"
            query = query.where(or_(Job.title.ilike(term), Job.company_name.ilike(term)))
        if status:
            query = query.where(Application.status == status)
        if location:
            query = query.where(Job.location.ilike(f"%{location.strip()}%"))
        if work_mode:
            query = query.where(Job.work_mode.ilike(work_mode))
        if date_from:
            query = query.where(Application.submitted_at >= datetime.combine(date_from, time.min, tzinfo=ZoneInfo("Asia/Kolkata")).astimezone(UTC))
        if date_to:
            query = query.where(Application.submitted_at < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=ZoneInfo("Asia/Kolkata")).astimezone(UTC))
        total = await self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        ordering = {"updated": Application.updated_at.desc(), "created": Application.created_at.desc(), "company": Job.company_name.asc(), "title": Job.title.asc()}.get(sort_by, Application.updated_at.desc())
        items = list(await self.session.scalars(query.order_by(ordering, Application.id).offset(offset).limit(limit)))
        return {"items": items, "total": int(total), "offset": offset, "limit": limit}

    async def upcoming(self, user_id: UUID, *, limit: int = 20):
        now = datetime.now(UTC)
        interviews = (await self.session.execute(select(Interview, Application, Job).join(Application, Application.id == Interview.application_id).join(Job, Job.id == Application.job_id).where(Interview.user_id == user_id, Interview.status == InterviewStatus.SCHEDULED, Interview.scheduled_at >= now).order_by(Interview.scheduled_at).limit(limit))).all()
        followups = (await self.session.execute(select(FollowUp, Application, Job).join(Application, Application.id == FollowUp.application_id).join(Job, Job.id == Application.job_id).where(FollowUp.user_id == user_id, FollowUp.status == FollowUpStatus.PENDING).order_by(FollowUp.due_at).limit(limit))).all()
        result = [{"kind": "INTERVIEW", "id": row.id, "application_id": app.id, "title": f"{row.interview_type} · {job.company_name}", "scheduled_at": row.scheduled_at, "timezone": row.timezone, "status": row.status.value, "job_title": job.title} for row, app, job in interviews]
        result += [{"kind": "FOLLOW_UP", "id": row.id, "application_id": app.id, "title": row.title, "scheduled_at": row.due_at, "timezone": row.timezone, "status": row.status.value, "job_title": job.title, "overdue": row.due_at < now} for row, app, job in followups]
        return sorted(result, key=lambda item: item["scheduled_at"])[:limit]

    async def timeline(self, user_id: UUID, application_id: UUID):
        app = await self.session.scalar(select(Application).where(Application.id == application_id, Application.user_id == user_id).options(selectinload(Application.job)))
        if app is None:
            return None
        audit_filter = or_(ApplicationAuditLog.application_id == application_id, ApplicationAuditLog.job_review_id == app.job_review_id) if app.job_review_id else ApplicationAuditLog.application_id == application_id
        logs = list(await self.session.scalars(select(ApplicationAuditLog).where(audit_filter).order_by(ApplicationAuditLog.occurred_at, ApplicationAuditLog.id)))
        app_events = list(await self.session.scalars(select(ApplicationEvent).where(ApplicationEvent.application_id == application_id).order_by(ApplicationEvent.occurred_at, ApplicationEvent.id)))
        reviews = []
        if app.job_review_id:
            reviews = list(await self.session.scalars(select(JobReviewEvent).where(JobReviewEvent.job_review_id == app.job_review_id).order_by(JobReviewEvent.created_at, JobReviewEvent.id)))
        timeline = [{"id": event.id, "event": event.event_type, "occurred_at": event.occurred_at, "details": event.metadata_json} for event in app_events]
        for log in logs:
            event_name = log.action
            if log.action == "APPLICATION_STATUS_UPDATED":
                if (log.details or {}).get("to") == ApplicationStatus.OFFER.value:
                    event_name = "OFFER_RECEIVED"
                elif (log.details or {}).get("to") == ApplicationStatus.INTERVIEW.value:
                    event_name = "INTERVIEW_STAGE_ENTERED"
            timeline.append({"id": log.id, "event": event_name, "occurred_at": log.occurred_at, "details": log.details})
        timeline += [{"id": event.id, "event": f"JOB_REVIEW_{event.status}", "occurred_at": event.created_at, "details": {"reason": event.rejection_reason}} for event in reviews]
        timeline.sort(key=lambda row: (row["occurred_at"], str(row["id"])))
        return {"application_id": app.id, "job": {"title": app.job.title, "company_name": app.job.company_name}, "timeline": timeline}

    async def analytics(self, user_id: UUID, start_date: date | None, end_date: date | None):
        start, end = _bounds(start_date, end_date)
        app_filter = [Application.user_id == user_id]
        if start:
            app_filter.append(Application.created_at >= start)
        if end:
            app_filter.append(Application.created_at < end)
        rows = (await self.session.execute(select(Application.status, func.count(Application.id)).where(*app_filter).group_by(Application.status))).all()
        by_status = {status.value: int(count) for status, count in rows}
        application_count = sum(by_status.values())
        submitted_filter = [Application.user_id == user_id, Application.submitted_at.is_not(None)]
        if start:
            submitted_filter.append(Application.submitted_at >= start)
        if end:
            submitted_filter.append(Application.submitted_at < end)
        submitted_ids = select(Application.id).where(*submitted_filter).subquery()
        applied = await self.session.scalar(select(func.count(distinct(submitted_ids.c.id)))) or 0
        interview_events = or_(ApplicationAuditLog.details["to"].as_string().in_(["INTERVIEW", "OFFER", "ACCEPTED"]), Application.status.in_([ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER, ApplicationStatus.ACCEPTED]))
        interview_query = select(func.count(distinct(Application.id))).outerjoin(ApplicationAuditLog, ApplicationAuditLog.application_id == Application.id).outerjoin(Interview, Interview.application_id == Application.id).where(*submitted_filter, or_(interview_events, Interview.id.is_not(None)))
        offer_events = or_(ApplicationAuditLog.details["to"].as_string().in_(["OFFER", "ACCEPTED"]), Application.status.in_([ApplicationStatus.OFFER, ApplicationStatus.ACCEPTED]))
        offer_query = select(func.count(distinct(Application.id))).outerjoin(ApplicationAuditLog, ApplicationAuditLog.application_id == Application.id).where(*submitted_filter, offer_events)
        interviews = await self.session.scalar(interview_query) or 0
        offers = await self.session.scalar(offer_query) or 0
        def conv(numerator: int) -> dict[str, int | float | bool | None]:
            return {"numerator": numerator, "denominator": applied, "percentage": round(numerator * 100 / applied, 1) if applied >= 5 else None, "sample_size_sufficient": applied >= 5}

        job_query = select(func.date_trunc("month", Job.first_seen_at).label("month"), func.count(distinct(Job.id))).join(JobSource).where(JobSource.user_id == user_id)
        if start:
            job_query = job_query.where(Job.first_seen_at >= start)
        if end:
            job_query = job_query.where(Job.first_seen_at < end)
        collected = [{"period": month.date().isoformat(), "count": int(count)} for month, count in (await self.session.execute(job_query.group_by("month").order_by("month"))).all()]

        ranked_matches = select(JobMatch.id.label("match_id"), JobMatch.job_id.label("job_id"), func.row_number().over(partition_by=JobMatch.job_id, order_by=(JobMatch.created_at.desc(), JobMatch.id.desc())).label("row_num")).where(JobMatch.user_id == user_id).subquery()
        bucket = case((JobMatch.overall_score >= 80, "80-100"), (JobMatch.overall_score >= 60, "60-79"), (JobMatch.overall_score >= 40, "40-59"), else_="0-39").label("score_bucket")
        match_query = select(bucket, func.count(JobMatch.id)).join(ranked_matches, ranked_matches.c.match_id == JobMatch.id).where(JobMatch.user_id == user_id, ranked_matches.c.row_num == 1)
        if start:
            match_query = match_query.where(JobMatch.created_at >= start)
        if end:
            match_query = match_query.where(JobMatch.created_at < end)
        match_distribution = {bucket_name: int(count) for bucket_name, count in (await self.session.execute(match_query.group_by(bucket).order_by(bucket))).all()}

        app_month = func.date_trunc("month", Application.created_at).label("app_month")
        app_timeline_query = select(app_month, func.count(Application.id)).where(*app_filter)
        app_timeline = [{"period": month.date().isoformat(), "count": int(count)} for month, count in (await self.session.execute(app_timeline_query.group_by(app_month).order_by(app_month))).all()]
        sources_query = select(JobSource.name, func.count(Application.id)).join(Job, Job.source_id == JobSource.id).join(Application, Application.job_id == Job.id).where(*app_filter).group_by(JobSource.name).order_by(func.count(Application.id).desc())
        source_distribution = [{"source": name, "count": int(count)} for name, count in (await self.session.execute(sources_query)).all()]
        return {"applications_by_status": by_status, "applications_over_time": app_timeline, "jobs_collected_over_time": collected,
                "match_distribution": match_distribution, "source_distribution": source_distribution,
                "interview_conversion": conv(interviews), "offer_conversion": conv(offers), "application_count": application_count,
                "date_range": {"start_date": start_date, "end_date": end_date}}
