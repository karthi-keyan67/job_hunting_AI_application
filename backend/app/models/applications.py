import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from app.models.base import Base, Timestamped, UUIDPrimaryKey, json_array_type, json_object_type
from app.models.enums import ApplicationStatus, ApprovalType, DraftStatus, DraftType

if TYPE_CHECKING:
    from app.models.account import ResumeVersion, User
    from app.models.jobs import Job, JobMatch, JobReview
    from app.models.tracking import FollowUp, Interview


class Application(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_applications_user_job"),
        Index("ix_applications_user_status", "user_id", "status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False)
    resume_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resume_versions.id", ondelete="RESTRICT"))
    job_match_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("job_matches.id", ondelete="SET NULL"))
    job_review_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("job_reviews.id", ondelete="SET NULL"))
    status: Mapped[ApplicationStatus] = mapped_column(Enum(ApplicationStatus, name="application_status"), default=ApplicationStatus.SAVED, nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    user: Mapped["User"] = relationship(back_populates="applications")
    job: Mapped["Job"] = relationship(back_populates="applications")
    events: Mapped[list["ApplicationEvent"]] = relationship(back_populates="application", cascade="all, delete-orphan")
    drafts: Mapped[list["ApplicationDraft"]] = relationship(back_populates="application", cascade="all, delete-orphan")
    approvals: Mapped[list["ApplicationApproval"]] = relationship(back_populates="application", cascade="all, delete-orphan")
    checklist: Mapped["ApplicationChecklist | None"] = relationship(back_populates="application", cascade="all, delete-orphan", uselist=False)
    audit_logs: Mapped[list["ApplicationAuditLog"]] = relationship(back_populates="application", cascade="all, delete-orphan")
    interviews: Mapped[list["Interview"]] = relationship(back_populates="application", cascade="all, delete-orphan")
    follow_ups: Mapped[list["FollowUp"]] = relationship(back_populates="application", cascade="all, delete-orphan")
    match: Mapped["JobMatch | None"] = relationship(foreign_keys=[job_match_id])
    resume_version: Mapped["ResumeVersion | None"] = relationship(foreign_keys=[resume_version_id])


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
        UniqueConstraint("application_id", "draft_type", "version", name="uq_application_drafts_app_type_version"),
        CheckConstraint("version > 0", name="version_positive"),
        Index("ix_application_drafts_app_type_created", "application_id", "draft_type", "created_at"),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(nullable=False)
    content: Mapped[dict] = mapped_column(json_object_type(), default=dict, nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    draft_type: Mapped[DraftType] = mapped_column(Enum(DraftType, name="application_draft_type"), default=DraftType.COVER_LETTER, nullable=False)
    status: Mapped[DraftStatus] = mapped_column(Enum(DraftStatus, name="application_draft_status"), default=DraftStatus.GENERATED, nullable=False)
    generated_by: Mapped[str] = mapped_column(String(40), default="AI", nullable=False)
    generation_model: Mapped[str | None] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(40), default="phase6-v1", nullable=False)
    evidence: Mapped[list] = mapped_column(json_array_type(), default=list, nullable=False)
    version_number = synonym("version")
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
    approver_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    draft_version_ids: Mapped[list] = mapped_column(json_array_type(), default=list, nullable=False)
    checklist_snapshot: Mapped[dict] = mapped_column(json_object_type(), default=dict, nullable=False)
    application: Mapped[Application] = relationship(back_populates="approvals")


class ApplicationChecklist(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "application_checklists"
    __table_args__ = (UniqueConstraint("application_id", name="uq_application_checklists_application_id"),)

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    checks: Mapped[dict] = mapped_column(json_object_type(), default=dict, nullable=False)
    application: Mapped[Application] = relationship(back_populates="checklist")


class ApplicationAuditLog(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "application_audit_logs"

    application_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("applications.id", ondelete="RESTRICT"), index=True)
    job_review_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("job_reviews.id", ondelete="RESTRICT"), index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    details: Mapped[dict] = mapped_column(json_object_type(), default=dict, nullable=False)
    actor: Mapped["User | None"] = relationship(back_populates="audit_logs")
    application: Mapped[Application | None] = relationship(back_populates="audit_logs")
    job_review: Mapped["JobReview | None"] = relationship(back_populates="audit_events")


class Notification(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read", "user_id", "is_read"), Index("ix_notifications_delivery", "delivery_status", "created_at"), UniqueConstraint("dedupe_key", name="uq_notifications_dedupe_key"))

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict] = mapped_column(json_object_type(), default=dict, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(240))
    delivery_status: Mapped[str] = mapped_column(String(20), default="PENDING", server_default="PENDING", nullable=False)
    delivery_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_delivery_error: Mapped[str | None] = mapped_column(Text)
    user: Mapped["User"] = relationship(back_populates="notifications")
