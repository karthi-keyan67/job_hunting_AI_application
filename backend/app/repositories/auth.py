from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import JobPreference, RefreshToken, User, UserProfile


class AuthRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_user_by_email(self, email: str) -> User | None:
        return await self.session.scalar(select(User).where(User.email == email))

    async def get_user(self, user_id: UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def create_user(self, email: str, password_hash: str) -> User:
        user = User(email=email, password_hash=password_hash)
        user.profile = UserProfile(currency="INR")
        user.preferences = JobPreference()
        self.session.add(user)
        await self.session.flush()
        return user

    async def add_refresh_token(self, user_id: UUID, token_hash: str, family_id: UUID, expires_at: datetime) -> RefreshToken:
        record = RefreshToken(user_id=user_id, token_hash=token_hash, family_id=family_id, expires_at=expires_at)
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_refresh_token(self, token_hash: str) -> RefreshToken | None:
        return await self.session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
        )

    async def revoke_token(self, record: RefreshToken, replacement_hash: str | None = None) -> None:
        record.revoked_at = datetime.now(timezone.utc)
        record.replaced_by_hash = replacement_hash
        await self.session.flush()

    async def revoke_family(self, family_id: UUID) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
        )

