from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.account import JobPreference, Resume, ResumeVersion, User, UserProfile
from app.models.jobs import Job, JobMatch, JobReview, MatchingRequestLimit


class MatchingRepository:
    def __init__(self, session):
        self.session = session

    async def load_inputs(self, user_id: UUID, resume_version_id: UUID | None):
        user = await self.session.get(User, user_id)
        profile = await self.session.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
        preferences = await self.session.scalar(select(JobPreference).where(JobPreference.user_id == user_id))
        if resume_version_id:
            version = await self.session.scalar(
                select(ResumeVersion).join(Resume).where(Resume.user_id == user_id, ResumeVersion.id == resume_version_id)
            )
        else:
            resume = await self.session.scalar(
                select(Resume).where(Resume.user_id == user_id, Resume.is_default.is_(True)).options(selectinload(Resume.versions))
            )
            version = max(resume.versions, key=lambda item: item.version_number) if resume and resume.versions else None
        return user, profile, preferences, version

    async def list_owned_jobs(self, user_id: UUID, job_ids: list[UUID] | None, maximum: int):
        query = select(Job).join(Job.source).where(Job.source.has(user_id=user_id), Job.status == "ACTIVE").options(selectinload(Job.skills), selectinload(Job.source))
        if job_ids is not None:
            if not job_ids:
                return []
            query = query.where(Job.id.in_(job_ids))
        query = query.order_by(Job.posted_at.desc().nullslast(), Job.created_at.desc()).limit(maximum + 1)
        jobs = list((await self.session.scalars(query)).unique().all())
        if len(jobs) > maximum:
            raise HTTPException(status_code=422, detail=f"A matching batch may contain at most {maximum} jobs")
        if job_ids and len(jobs) != len(set(job_ids)):
            raise HTTPException(status_code=404, detail="One or more jobs were not found")
        return jobs

    async def find_cached(self, user_id: UUID, job_id: UUID, fingerprint: str):
        return await self.session.scalar(select(JobMatch).where(JobMatch.user_id == user_id, JobMatch.job_id == job_id, JobMatch.input_fingerprint == fingerprint))

    async def save_idempotent(self, row: JobMatch):
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
            return row
        except IntegrityError:
            existing = await self.find_cached(row.user_id, row.job_id, row.input_fingerprint)
            if existing is None:
                raise
            return existing

    async def list_results(self, user_id: UUID, *, min_score=None, location=None, work_mode=None, skill=None, source_id=None, eligibility=None, review_status=None):
        query = select(JobMatch, Job).join(Job, Job.id == JobMatch.job_id).join(Job.source).outerjoin(JobReview, and_(JobReview.job_id == Job.id, JobReview.user_id == user_id)).where(JobMatch.user_id == user_id, Job.source.has(user_id=user_id)).options(selectinload(Job.skills), selectinload(Job.source))
        if min_score is not None:
            query = query.where(JobMatch.overall_score >= min_score)
        if eligibility:
            query = query.where(JobMatch.eligibility_status == eligibility.upper())
        if review_status:
            query = query.where(JobReview.status == review_status.upper())
        if source_id:
            query = query.where(Job.source_id == source_id)
        if location:
            query = query.where(Job.location.ilike(f"%{location}%"))
        if work_mode:
            query = query.where(Job.work_mode.ilike(work_mode))
        query = query.order_by(JobMatch.overall_score.desc(), JobMatch.created_at.desc())
        rows = list((await self.session.execute(query)).unique().all())
        if skill:
            canonical = skill.casefold().strip()
            rows = [(match, job) for match, job in rows if canonical in {value.casefold().strip() for value in (match.matched_skills or [])}]
        return rows

    async def get_owned_result(self, user_id: UUID, match_id: UUID):
        query = select(JobMatch, Job).join(Job, Job.id == JobMatch.job_id).join(Job.source).where(
            JobMatch.id == match_id, JobMatch.user_id == user_id, Job.source.has(user_id=user_id)
        ).options(selectinload(Job.skills), selectinload(Job.source))
        return (await self.session.execute(query)).unique().first()

    async def list_matches(self, user_id: UUID):
        return list((await self.session.scalars(select(JobMatch).where(JobMatch.user_id == user_id))).all())

    async def enforce_rate_limit(self, user_id: UUID, per_minute: int):
        now = datetime.now(UTC).replace(second=0, microsecond=0)
        await self.session.execute(delete(MatchingRequestLimit).where(MatchingRequestLimit.window_started_at < now - timedelta(days=2)))
        table = MatchingRequestLimit.__table__
        statement = pg_insert(MatchingRequestLimit).values(user_id=user_id, window_started_at=now, request_count=1)
        statement = statement.on_conflict_do_update(
            constraint="uq_matching_request_limits_user_window",
            set_={"request_count": table.c.request_count + 1},
            where=table.c.request_count < per_minute,
        ).returning(MatchingRequestLimit.id)
        if (await self.session.scalar(statement)) is None:
            raise HTTPException(status_code=429, detail="Matching request rate limit exceeded")
