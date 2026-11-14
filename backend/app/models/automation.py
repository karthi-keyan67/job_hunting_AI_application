import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamped, UUIDPrimaryKey, json_array_type, json_object_type


class AutomationSettings(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "automation_settings"
    __table_args__ = (UniqueConstraint("user_id", name="uq_automation_settings_user_id"), CheckConstraint("minimum_match_score >= 0 AND minimum_match_score <= 100", name="match_score_range"))

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Kolkata", server_default="Asia/Kolkata", nullable=False)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    notify_job_matches: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    notify_collection: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    notify_reminders: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    minimum_match_score: Mapped[int] = mapped_column(Integer, default=75, server_default="75", nullable=False)
    quiet_start: Mapped[str | None] = mapped_column(String(5))
    quiet_end: Mapped[str | None] = mapped_column(String(5))
    reminder_intervals_minutes: Mapped[list[int]] = mapped_column(json_array_type(), default=lambda: [1440, 60], nullable=False)
    user = relationship("User", back_populates="automation_settings")


class AutomationExecution(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "automation_executions"
    __table_args__ = (UniqueConstraint("run_key", name="uq_automation_executions_run_key"), Index("ix_automation_executions_status_started", "status", "started_at"))

    run_key: Mapped[str] = mapped_column(String(120), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[float | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), default="PENDING", server_default="PENDING", nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    error_details: Mapped[dict] = mapped_column(json_object_type(), default=dict, nullable=False)


class WorkerHeartbeat(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "worker_heartbeats"
    __table_args__ = (UniqueConstraint("worker_name", name="uq_worker_heartbeats_worker_name"),)

    worker_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="STARTING", server_default="STARTING", nullable=False)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict] = mapped_column(json_object_type(), default=dict, nullable=False)

