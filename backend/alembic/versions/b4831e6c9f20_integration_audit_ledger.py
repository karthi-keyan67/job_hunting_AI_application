"""Add an integration-specific audit ledger.

Revision ID: b4831e6c9f20
Revises: a17f4c29d6b1
Create Date: 2026-11-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "b4831e6c9f20"
down_revision: Union[str, None] = "a17f4c29d6b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "integration_audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("platform", sa.String(length=30), nullable=False),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["job_sources.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_integration_audit_user_occurred", "integration_audit_logs", ["user_id", "occurred_at"])
    op.create_index("ix_integration_audit_user_platform_occurred", "integration_audit_logs", ["user_id", "platform", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_integration_audit_user_platform_occurred", table_name="integration_audit_logs")
    op.drop_index("ix_integration_audit_user_occurred", table_name="integration_audit_logs")
    op.drop_table("integration_audit_logs")
