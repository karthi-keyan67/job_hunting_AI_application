import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamped, UUIDPrimaryKey, json_array_type, json_object_type

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


class GmailAlertReview(UUIDPrimaryKey, Timestamped, Base):
    """Per-user idempotency ledger and review queue for Gmail alert messages."""
    __tablename__ = "gmail_alert_reviews"
    __table_args__ = (
        UniqueConstraint("source_id", "gmail_message_id", name="uq_gmail_alert_reviews_source_message"),
        Index("ix_gmail_alert_reviews_user_status_received", "user_id", "status", "received_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job_sources.id", ondelete="CASCADE"), nullable=False)
    gmail_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    sender: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(998), default="", nullable=False)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="NEEDS_REVIEW", server_default="NEEDS_REVIEW", nullable=False)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, default="", nullable=False)


class IntegrationAuditLog(UUIDPrimaryKey, Base):
    """Append-only record of user initiated integration and source setting changes."""
    __tablename__ = "integration_audit_logs"
    __table_args__ = (
        Index("ix_integration_audit_user_occurred", "user_id", "occurred_at"),
        Index("ix_integration_audit_user_platform_occurred", "user_id", "platform", "occurred_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("job_sources.id", ondelete="SET NULL"))
    platform: Mapped[str] = mapped_column(String(30), nullable=False)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    details: Mapped[dict] = mapped_column(json_object_type(), default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
