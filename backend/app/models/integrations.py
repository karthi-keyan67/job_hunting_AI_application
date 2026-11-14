import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamped, UUIDPrimaryKey, json_array_type

if TYPE_CHECKING:
    from app.models.account import User


class GoogleOAuthState(UUIDPrimaryKey, Base):
    __tablename__ = "google_oauth_states"
    __table_args__ = (
        UniqueConstraint("state_hash", name="uq_google_oauth_states_state_hash"),
        Index("ix_google_oauth_states_expires_at", "expires_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped["User"] = relationship(back_populates="google_oauth_states")


class GoogleOAuthConnection(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "google_oauth_connections"
    __table_args__ = (UniqueConstraint("user_id", name="uq_google_oauth_connections_user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    gmail_address: Mapped[str | None] = mapped_column(String(320))
    encrypted_credentials: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(json_array_type(), default=list, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped["User"] = relationship(back_populates="google_oauth_connection")
