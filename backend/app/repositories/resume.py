from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.account import Resume, ResumeVersion


class ResumeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_for_user(self, user_id: UUID) -> list[Resume]:
        result = await self.session.scalars(
            select(Resume).where(Resume.user_id == user_id).options(selectinload(Resume.versions)).order_by(Resume.created_at.desc())
        )
        return list(result.unique().all())

    async def get(self, resume_id: UUID, user_id: UUID, *, lock: bool = False) -> Resume | None:
        statement = (
            select(Resume)
            .where(Resume.id == resume_id, Resume.user_id == user_id)
            .options(selectinload(Resume.versions))
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def get_version(self, resume_id: UUID, version_id: UUID) -> ResumeVersion | None:
        return await self.session.scalar(select(ResumeVersion).where(ResumeVersion.resume_id == resume_id, ResumeVersion.id == version_id))
