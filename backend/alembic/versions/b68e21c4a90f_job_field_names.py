"""Add exact Phase 4 names while retaining legacy compatibility columns.

Revision ID: b68e21c4a90f
Revises: a7d91b2f4c30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "b68e21c4a90f"
down_revision: Union[str, None] = "a7d91b2f4c30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("job_skills", sa.Column("skill_name", sa.String(120), nullable=True))
    op.execute("UPDATE job_skills SET skill_name = skill")
    op.alter_column("job_skills", "skill_name", nullable=False)
    op.create_unique_constraint(op.f("uq_job_skills_job_skill_name_type"), "job_skills", ["job_id", "skill_name", "skill_type"])

    op.add_column("collection_runs", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("collection_runs", sa.Column("error_message", sa.Text(), nullable=True))
    op.add_column("collection_runs", sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.execute("UPDATE collection_runs SET completed_at = finished_at, error_message = error_summary, metadata = COALESCE(statistics, '{}'::jsonb)")


def downgrade() -> None:
    op.drop_column("collection_runs", "metadata")
    op.drop_column("collection_runs", "error_message")
    op.drop_column("collection_runs", "completed_at")
    op.drop_constraint(op.f("uq_job_skills_job_skill_name_type"), "job_skills", type_="unique")
    op.drop_column("job_skills", "skill_name")
