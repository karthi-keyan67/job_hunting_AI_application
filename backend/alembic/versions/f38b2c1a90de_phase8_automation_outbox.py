"""Phase 8 automation state and notification outbox.

Revision ID: f38b2c1a90de
Revises: e4a62f8b13c7
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f38b2c1a90de"
down_revision: Union[str, None] = "e4a62f8b13c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("collection_runs", sa.Column("duration_seconds", sa.Float(), nullable=True))
    op.add_column("collection_runs", sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("notifications", sa.Column("dedupe_key", sa.String(240), nullable=True))
    op.add_column("notifications", sa.Column("delivery_status", sa.String(20), server_default="PENDING", nullable=False))
    op.add_column("notifications", sa.Column("delivery_attempts", sa.Integer(), server_default="0", nullable=False))
    op.add_column("notifications", sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("notifications", sa.Column("last_delivery_error", sa.Text(), nullable=True))
    op.create_unique_constraint("uq_notifications_dedupe_key", "notifications", ["dedupe_key"])
    op.create_index("ix_notifications_delivery", "notifications", ["delivery_status", "created_at"])

    op.create_table(
        "automation_settings",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("timezone", sa.String(80), server_default="Asia/Kolkata", nullable=False),
        sa.Column("email_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("notify_job_matches", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("notify_collection", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("notify_reminders", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("minimum_match_score", sa.Integer(), server_default="75", nullable=False),
        sa.Column("quiet_start", sa.String(5)), sa.Column("quiet_end", sa.String(5)),
        sa.Column("reminder_intervals_minutes", postgresql.JSONB(), server_default='[1440, 60]', nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("minimum_match_score >= 0 AND minimum_match_score <= 100", name="ck_automation_settings_match_score_range"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_automation_settings_user_id"),
    )
    op.create_table(
        "automation_executions",
        sa.Column("run_key", sa.String(120), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("duration_seconds", sa.Float()), sa.Column("status", sa.String(20), server_default="PENDING", nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_details", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("run_key", name="uq_automation_executions_run_key"),
    )
    op.create_index("ix_automation_executions_status_started", "automation_executions", ["status", "started_at"])
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_name", sa.String(100), nullable=False), sa.Column("status", sa.String(20), server_default="STARTING", nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True)), sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("details", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("worker_name", name="uq_worker_heartbeats_worker_name"),
    )


def downgrade() -> None:
    op.drop_table("worker_heartbeats")
    op.drop_index("ix_automation_executions_status_started", table_name="automation_executions")
    op.drop_table("automation_executions")
    op.drop_table("automation_settings")
    op.drop_index("ix_notifications_delivery", table_name="notifications")
    op.drop_constraint("uq_notifications_dedupe_key", "notifications", type_="unique")
    for column in ("last_delivery_error", "delivered_at", "delivery_attempts", "delivery_status", "dedupe_key"):
        op.drop_column("notifications", column)
    op.drop_column("collection_runs", "retry_count")
    op.drop_column("collection_runs", "duration_seconds")
