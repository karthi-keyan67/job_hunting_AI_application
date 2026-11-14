import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamped, UUIDPrimaryKey
from app.models.enums import FollowUpStatus, InterviewStatus

if TYPE_CHECKING:
    from app.models.applications import Application


class Interview(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "interviews"
    __table_args__ = (
        Index("ix_interviews_user_scheduled", "user_id", "scheduled_at"),
        Index("ix_interviews_application_scheduled", "application_id", "scheduled_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    interview_type: Mapped[str] = mapped_column(String(80), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Kolkata", server_default="Asia/Kolkata", nullable=False)
    meeting_url: Mapped[str | None] = mapped_column(Text)
    interviewer_name: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[InterviewStatus] = mapped_column(Enum(InterviewStatus, name="interview_status"), default=InterviewStatus.SCHEDULED, server_default="SCHEDULED", nullable=False)
    application: Mapped["Application"] = relationship(back_populates="interviews")


class FollowUp(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "follow_ups"
    __table_args__ = (
        Index("ix_follow_ups_user_due", "user_id", "due_at"),
        Index("ix_follow_ups_application_due", "application_id", "due_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Kolkata", server_default="Asia/Kolkata", nullable=False)
    status: Mapped[FollowUpStatus] = mapped_column(Enum(FollowUpStatus, name="follow_up_status"), default=FollowUpStatus.PENDING, server_default="PENDING", nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    application: Mapped["Application"] = relationship(back_populates="follow_ups")
