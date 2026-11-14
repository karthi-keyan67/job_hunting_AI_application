from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import JobPreference, UserProfile


class ProfileRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_profile(self, user_id: UUID) -> UserProfile | None:
        return await self.session.scalar(select(UserProfile).where(UserProfile.user_id == user_id))

    async def save_profile(self, user_id: UUID, values: dict) -> UserProfile:
        profile = await self.get_profile(user_id)
        if profile is None:
            profile = UserProfile(user_id=user_id)
            self.session.add(profile)
        for key, value in values.items():
            setattr(profile, key, value)
        await self.session.flush()
        return profile

    async def get_preferences(self, user_id: UUID) -> JobPreference | None:
        return await self.session.scalar(select(JobPreference).where(JobPreference.user_id == user_id))

    async def save_preferences(self, user_id: UUID, values: dict) -> JobPreference:
        preferences = await self.get_preferences(user_id)
        if preferences is None:
            preferences = JobPreference(user_id=user_id)
            self.session.add(preferences)
        for key, value in values.items():
            setattr(preferences, key, value)
        await self.session.flush()
        return preferences
