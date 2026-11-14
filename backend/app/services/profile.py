from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.profile import ProfileRepository


class ProfileService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = ProfileRepository(session)

    async def get_profile(self, user_id: UUID):
        profile = await self.repository.get_profile(user_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        return profile

    async def update_profile(self, user_id: UUID, values: dict):
        profile = await self.repository.save_profile(user_id, values)
        await self.session.commit()
        await self.session.refresh(profile)
        return profile

    async def get_preferences(self, user_id: UUID):
        preferences = await self.repository.get_preferences(user_id)
        if preferences is None:
            raise HTTPException(status_code=404, detail="Job preferences not found")
        return preferences

    async def update_preferences(self, user_id: UUID, values: dict):
        preferences = await self.repository.save_preferences(user_id, values)
        await self.session.commit()
        await self.session.refresh(preferences)
        return preferences
