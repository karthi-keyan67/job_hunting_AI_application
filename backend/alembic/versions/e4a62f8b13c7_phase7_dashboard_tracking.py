"""Add interview and follow-up tracking for Phase 7.

Revision ID: e4a62f8b13c7
Revises: d63fa8bc1201
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "e4a62f8b13c7"
down_revision: Union[str, None] = "d63fa8bc1201"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

interview_status = postgresql.ENUM("SCHEDULED", "COMPLETED", "CANCELLED", name="interview_status", create_type=False)
follow_up_status = postgresql.ENUM("PENDING", "COMPLETED", "CANCELLED", name="follow_up_status", create_type=False)


def upgrade() -> None:
    interview_status.create(op.get_bind(), checkfirst=True)
    follow_up_status.create(op.get_bind(), checkfirst=True)
    op.add_column("applications", sa.Column("notes", sa.Text(), nullable=True))
    op.create_table(
        "interviews",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("interview_type", sa.String(length=80), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(length=80), server_default="Asia/Kolkata", nullable=False),
        sa.Column("meeting_url", sa.Text(), nullable=True),
        sa.Column("interviewer_name", sa.String(length=200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", interview_status, server_default="SCHEDULED", nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_interviews_user_scheduled", "interviews", ["user_id", "scheduled_at"])
    op.create_index("ix_interviews_application_scheduled", "interviews", ["application_id", "scheduled_at"])
    op.create_table(
        "follow_ups",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(length=80), server_default="Asia/Kolkata", nullable=False),
        sa.Column("status", follow_up_status, server_default="PENDING", nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_follow_ups_user_due", "follow_ups", ["user_id", "due_at"])
    op.create_index("ix_follow_ups_application_due", "follow_ups", ["application_id", "due_at"])


def downgrade() -> None:
    op.drop_index("ix_follow_ups_application_due", table_name="follow_ups")
    op.drop_index("ix_follow_ups_user_due", table_name="follow_ups")
    op.drop_table("follow_ups")
    op.drop_index("ix_interviews_application_scheduled", table_name="interviews")
    op.drop_index("ix_interviews_user_scheduled", table_name="interviews")
    op.drop_table("interviews")
    op.drop_column("applications", "notes")
    follow_up_status.drop(op.get_bind(), checkfirst=True)
    interview_status.drop(op.get_bind(), checkfirst=True)
