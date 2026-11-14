"""Add privacy-preserving PostgreSQL login throttling state.

Revision ID: f18a3d7c9b20
Revises: e26b7a10c94d
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f18a3d7c9b20"
down_revision: Union[str, None] = "e26b7a10c94d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "auth_login_attempts",
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("window_started", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("attempts > 0", name="ck_auth_login_attempts_attempts_positive"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash", name="uq_auth_login_attempts_key_hash"),
    )
    op.create_index("ix_auth_login_attempts_window_started", "auth_login_attempts", ["window_started"])


def downgrade() -> None:
    op.drop_index("ix_auth_login_attempts_window_started", table_name="auth_login_attempts")
    op.drop_table("auth_login_attempts")
