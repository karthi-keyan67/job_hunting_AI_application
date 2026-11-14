"""Create default automation preferences for existing accounts.

Revision ID: e26b7a10c94d
Revises: d0e4f26b8a31
"""
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "e26b7a10c94d"
down_revision: Union[str, None] = "d0e4f26b8a31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_users = bind.execute(sa.text("SELECT id FROM users WHERE id NOT IN (SELECT user_id FROM automation_settings)")).scalars().all()
    table = sa.table("automation_settings", sa.column("id", postgresql.UUID(as_uuid=True)), sa.column("user_id", postgresql.UUID(as_uuid=True)))
    if existing_users:
        op.bulk_insert(table, [{"id": uuid4(), "user_id": user_id} for user_id in existing_users])


def downgrade() -> None:
    # Retain user-editable preference rows; deleting them on downgrade would lose data.
    pass
