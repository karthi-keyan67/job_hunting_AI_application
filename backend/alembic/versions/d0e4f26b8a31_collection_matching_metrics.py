"""Record matching performance alongside collection runs.

Revision ID: d0e4f26b8a31
Revises: c91e4d6a2f70
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d0e4f26b8a31"
down_revision: Union[str, None] = "c91e4d6a2f70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("collection_runs", sa.Column("matching_duration_seconds", sa.Float(), nullable=True))
    op.add_column("collection_runs", sa.Column("matching_failed", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    op.drop_column("collection_runs", "matching_failed")
    op.drop_column("collection_runs", "matching_duration_seconds")
