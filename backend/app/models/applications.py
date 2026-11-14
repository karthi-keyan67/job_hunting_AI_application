import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamped, UUIDPrimaryKey, json_object_type
from app.models.enums import ApplicationStatus, ApprovalType


class Application(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_applications_user_job"),
        Index("ix_applications_user_status", "user_id", "status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[ApplicationStatus] = mapped_column(Enum(ApplicationStatus, name="application_status"), default=ApplicationStatus.SAVED, nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped["User"] = relationship(back_populates="applications")
    job: Mapped["Job"] = relationship(back_populates="applications")
    events: Mapped[list["ApplicationEvent"]] = relationship(back_populates="application", cascade="all, delete-orphan")
    drafts: Mapped[list["ApplicationDraft"]] = relationship(back_populates="application", cascade="all, delete-orphan")
    approvals: Mapped[list["ApplicationApproval"]] = relationship(back_populates="application", cascade="all, delete-orphan")
    checklist: Mapped["ApplicationChecklist | None"] = relationship(back_populates="application", cascade="all, delete-orphan", uselist=False)
    audit_logs: Mapped[list["ApplicationAuditLog"]] = relationship(back_populates="application", cascade="all, delete-orphan")


class ApplicationEvent(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "application_events"

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(json_object_type(), default=dict, nullable=False)
    application: Mapped[Application] = relationship(back_populates="events")


class ApplicationDraft(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "application_drafts"
    __table_args__ = (
        UniqueConstraint("application_id", "version", name="uq_application_drafts_application_version"),
        CheckConstraint("version > 0", name="version_positive"),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(nullable=False)
    content: Mapped[dict] = mapped_column(json_object_type(), default=dict, nullable=False)
    application: Mapped[Application] = relationship(back_populates="drafts")


class ApplicationApproval(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "application_approvals"
    __table_args__ = (
        UniqueConstraint("application_id", "approval_type", name="uq_application_approvals_application_type"),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    approval_type: Mapped[ApprovalType] = mapped_column(Enum(ApprovalType, name="application_approval_type"), nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    application: Mapped[Application] = relationship(back_populates="approvals")


class ApplicationChecklist(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "application_checklists"
    __table_args__ = (UniqueConstraint("application_id", name="uq_application_checklists_application_id"),)

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    checks: Mapped[dict] = mapped_column(json_object_type(), default=dict, nullable=False)
    application: Mapped[Application] = relationship(back_populates="checklist")


class ApplicationAuditLog(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "application_audit_logs"

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    details: Mapped[dict] = mapped_column(json_object_type(), default=dict, nullable=False)
    actor: Mapped["User | None"] = relationship(back_populates="audit_logs")
    application: Mapped[Application] = relationship(back_populates="audit_logs")


class Notification(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read", "user_id", "is_read"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict] = mapped_column(json_object_type(), default=dict, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    user: Mapped["User"] = relationship(back_populates="notifications")
