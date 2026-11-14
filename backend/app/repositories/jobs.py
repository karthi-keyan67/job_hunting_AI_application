from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.jobs import CollectionRun, Job, JobDuplicate, JobSource


class JobRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_sources(self, user_id: UUID) -> list[JobSource]:
        return list((await self.session.scalars(select(JobSource).where(JobSource.user_id == user_id).order_by(JobSource.created_at.desc()))).all())

    async def get_source(self, source_id: UUID, user_id: UUID, *, lock: bool = False) -> JobSource | None:
        query = select(JobSource).where(JobSource.id == source_id, JobSource.user_id == user_id)
        if lock:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def get_job(self, job_id: UUID, user_id: UUID) -> Job | None:
        return await self.session.scalar(
            select(Job).join(JobSource, Job.source_id == JobSource.id)
            .where(Job.id == job_id, JobSource.user_id == user_id)
            .options(selectinload(Job.source), selectinload(Job.skills))
            .execution_options(populate_existing=True)
        )

    async def list_jobs(self, user_id: UUID, *, search: str | None, location: str | None, work_mode: str | None,
                        source_id: UUID | None, offset: int, limit: int) -> tuple[list[Job], int]:
        query = select(Job).join(JobSource, Job.source_id == JobSource.id).where(JobSource.user_id == user_id)
        if search:
            term = f"%{search.strip()}%"
            query = query.where(Job.title.ilike(term) | Job.company_name.ilike(term))
        if location:
            query = query.where(Job.location.ilike(f"%{location.strip()}%"))
        if work_mode:
            query = query.where(Job.work_mode == work_mode.upper())
        if source_id:
            query = query.where(Job.source_id == source_id)
        total = await self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        records = await self.session.scalars(query.options(selectinload(Job.source), selectinload(Job.skills)).order_by(Job.last_seen_at.desc()).offset(offset).limit(limit))
        return list(records.unique().all()), total

    async def runs_for_source(self, source_id: UUID) -> list[CollectionRun]:
        records = await self.session.scalars(select(CollectionRun).where(CollectionRun.source_id == source_id).order_by(CollectionRun.started_at.desc()).limit(100))
        return list(records.all())

    async def all_runs(self, user_id: UUID) -> list[CollectionRun]:
        records = await self.session.scalars(
            select(CollectionRun).join(JobSource, CollectionRun.source_id == JobSource.id)
            .where(JobSource.user_id == user_id).order_by(CollectionRun.started_at.desc()).limit(100)
        )
        return list(records.all())

    async def has_jobs(self, source_id: UUID) -> bool:
        return bool(await self.session.scalar(select(Job.id).where(Job.source_id == source_id).limit(1)))

    async def has_duplicate(self, job_id: UUID) -> bool:
        return bool(await self.session.scalar(select(JobDuplicate.id).where((JobDuplicate.job_id == job_id) | (JobDuplicate.duplicate_job_id == job_id)).limit(1)))
