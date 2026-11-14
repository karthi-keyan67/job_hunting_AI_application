from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integrations import GoogleOAuthConnection, GoogleOAuthState


class GoogleOAuthRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_state(self, user_id: UUID, state_hash: str, expires_at: datetime) -> GoogleOAuthState:
        await self.session.execute(
            delete(GoogleOAuthState).where(GoogleOAuthState.expires_at < datetime.now(timezone.utc) - timedelta(days=1))
        )
        state = GoogleOAuthState(user_id=user_id, state_hash=state_hash, expires_at=expires_at)
        self.session.add(state)
        await self.session.flush()
        return state

    async def get_state(self, state_hash: str, *, lock: bool = False) -> GoogleOAuthState | None:
        query = select(GoogleOAuthState).where(GoogleOAuthState.state_hash == state_hash)
        if lock:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def get_connection(self, user_id: UUID, *, lock: bool = False) -> GoogleOAuthConnection | None:
        query = select(GoogleOAuthConnection).where(GoogleOAuthConnection.user_id == user_id)
        if lock:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def save_connection(
        self,
        user_id: UUID,
        encrypted_credentials: str,
        scopes: list[str],
        expires_at: datetime | None,
        gmail_address: str | None = None,
    ) -> GoogleOAuthConnection:
        row = await self.get_connection(user_id, lock=True)
        if row is None:
            row = GoogleOAuthConnection(user_id=user_id, encrypted_credentials=encrypted_credentials, scopes=scopes, expires_at=expires_at, gmail_address=gmail_address)
            self.session.add(row)
        else:
            row.encrypted_credentials = encrypted_credentials
            row.scopes = scopes
            row.expires_at = expires_at
            row.gmail_address = gmail_address or row.gmail_address
            row.revoked_at = None
        await self.session.flush()
        return row
