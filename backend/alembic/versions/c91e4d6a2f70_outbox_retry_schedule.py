"""Persist retry schedule for notification outbox.

Revision ID: c91e4d6a2f70
Revises: f38b2c1a90de
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c91e4d6a2f70"
down_revision: Union[str, None] = "f38b2c1a90de"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("notifications", "next_attempt_at")
