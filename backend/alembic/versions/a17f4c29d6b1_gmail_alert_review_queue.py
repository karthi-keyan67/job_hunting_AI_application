"""Add durable Gmail alert idempotency and review queue."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a17f4c29d6b1"
down_revision: Union[str, None] = "a9210df6c5be"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gmail_alert_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gmail_message_id", sa.String(length=255), nullable=False),
        sa.Column("sender", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=998), server_default="", nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="NEEDS_REVIEW", nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column("excerpt", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["job_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "gmail_message_id", name="uq_gmail_alert_reviews_source_message"),
    )
    op.create_index("ix_gmail_alert_reviews_user_status_received", "gmail_alert_reviews", ["user_id", "status", "received_at"])


def downgrade() -> None:
    op.drop_index("ix_gmail_alert_reviews_user_status_received", table_name="gmail_alert_reviews")
    op.drop_table("gmail_alert_reviews")
