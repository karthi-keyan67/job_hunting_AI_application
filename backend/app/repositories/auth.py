from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import case, delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import AuthLoginAttempt, JobPreference, RefreshToken, User, UserProfile
from app.models.automation import AutomationSettings


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
        user.automation_settings = AutomationSettings()
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

    async def record_login_attempt(self, key_hash: str, window_started: datetime) -> int:
        statement = insert(AuthLoginAttempt).values(key_hash=key_hash, window_started=window_started, attempts=1)
        statement = statement.on_conflict_do_update(
            index_elements=[AuthLoginAttempt.key_hash],
            set_={
                "attempts": case(
                    (AuthLoginAttempt.window_started < window_started, 1),
                    else_=AuthLoginAttempt.attempts + 1,
                ),
                "window_started": window_started,
            },
        ).returning(AuthLoginAttempt.attempts)
        attempts = int(await self.session.scalar(statement))
        stale_ids = select(AuthLoginAttempt.id).where(
            AuthLoginAttempt.window_started < datetime.now(timezone.utc) - timedelta(days=2)
        ).limit(100)
        await self.session.execute(delete(AuthLoginAttempt).where(AuthLoginAttempt.id.in_(stale_ids)))
        return attempts

    async def clear_login_attempt(self, key_hash: str) -> None:
        await self.session.execute(delete(AuthLoginAttempt).where(AuthLoginAttempt.key_hash == key_hash))

