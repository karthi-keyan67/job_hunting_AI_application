"""Add owned sources, normalized job metadata, collection accounting and duplicate provenance.

Revision ID: a7d91b2f4c30
Revises: 83b5a91c2e47
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a7d91b2f4c30"
down_revision: Union[str, None] = "83b5a91c2e47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("job_sources", sa.Column("source_type", sa.String(80), nullable=True))
    op.add_column("job_sources", sa.Column("user_id", sa.UUID(), nullable=True))
    op.add_column("job_sources", sa.Column("base_url", sa.Text(), nullable=True))
    op.add_column("job_sources", sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("job_sources", sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("job_sources", sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE job_sources SET source_type = connector_type, base_url = configuration ->> 'base_url', is_enabled = (status = 'ENABLED')")
    op.alter_column("job_sources", "source_type", nullable=False)
    op.create_foreign_key(op.f("fk_job_sources_user_id_users"), "job_sources", "users", ["user_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_job_sources_user_id", "job_sources", ["user_id"])

    op.add_column("jobs", sa.Column("employment_type", sa.String(40), nullable=True))
    op.add_column("jobs", sa.Column("salary_period", sa.String(16), nullable=True))
    op.add_column("jobs", sa.Column("salary_min", sa.Numeric(12, 2), nullable=True))
    op.add_column("jobs", sa.Column("salary_max", sa.Numeric(12, 2), nullable=True))
    op.add_column("jobs", sa.Column("experience_min", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("experience_max", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("job_url", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("apply_url", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("content_hash", sa.String(64), nullable=True))
    op.add_column("jobs", sa.Column("raw_data", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column("jobs", sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False))
    op.add_column("jobs", sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False))
    op.add_column("jobs", sa.Column("status", sa.String(20), server_default="ACTIVE", nullable=False))
    op.execute("UPDATE jobs SET apply_url = application_url, raw_data = COALESCE(metadata_json, '{}'::jsonb), salary_min = salary_minimum, salary_max = salary_maximum, experience_min = experience_minimum_months, experience_max = experience_maximum_months, first_seen_at = created_at, last_seen_at = updated_at")
    op.create_index("ix_jobs_content_hash", "jobs", ["content_hash"])
    op.create_index("ix_jobs_status_last_seen", "jobs", ["status", "last_seen_at"])

    op.add_column("job_skills", sa.Column("skill_type", sa.String(20), server_default="REQUIRED", nullable=False))
    op.execute("UPDATE job_skills SET skill_type = CASE WHEN is_required THEN 'REQUIRED' ELSE 'PREFERRED' END")

    op.add_column("collection_runs", sa.Column("jobs_found", sa.Integer(), server_default="0", nullable=False))
    op.add_column("collection_runs", sa.Column("jobs_created", sa.Integer(), server_default="0", nullable=False))
    op.add_column("collection_runs", sa.Column("jobs_updated", sa.Integer(), server_default="0", nullable=False))
    op.add_column("collection_runs", sa.Column("jobs_skipped", sa.Integer(), server_default="0", nullable=False))
    op.create_index(
        "uq_collection_runs_one_running_per_source",
        "collection_runs",
        ["source_id"],
        unique=True,
        postgresql_where=sa.text("status = 'RUNNING'"),
    )

    op.create_table(
        "job_duplicates",
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("duplicate_job_id", sa.UUID(), nullable=False),
        sa.Column("match_reason", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("job_id <> duplicate_job_id", name=op.f("ck_job_duplicates_jobs_must_differ")),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE", name=op.f("fk_job_duplicates_job_id_jobs")),
        sa.ForeignKeyConstraint(["duplicate_job_id"], ["jobs.id"], ondelete="CASCADE", name=op.f("fk_job_duplicates_duplicate_job_id_jobs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_duplicates")),
        sa.UniqueConstraint("job_id", "duplicate_job_id", name="uq_job_duplicates_pair"),
    )
    op.create_index("ix_job_duplicates_duplicate_job_id", "job_duplicates", ["duplicate_job_id"])


def downgrade() -> None:
    op.drop_index("ix_job_duplicates_duplicate_job_id", table_name="job_duplicates")
    op.drop_table("job_duplicates")
    op.drop_index("uq_collection_runs_one_running_per_source", table_name="collection_runs")
    for column in ("jobs_skipped", "jobs_updated", "jobs_created", "jobs_found"):
        op.drop_column("collection_runs", column)
    op.drop_column("job_skills", "skill_type")
    op.drop_index("ix_jobs_status_last_seen", table_name="jobs")
    op.drop_index("ix_jobs_content_hash", table_name="jobs")
    for column in ("status", "last_seen_at", "first_seen_at", "raw_data", "content_hash", "apply_url", "job_url", "experience_max", "experience_min", "salary_max", "salary_min", "salary_period", "employment_type"):
        op.drop_column("jobs", column)
    op.drop_index("ix_job_sources_user_id", table_name="job_sources")
    op.drop_constraint(op.f("fk_job_sources_user_id_users"), "job_sources", type_="foreignkey")
    for column in ("last_failure_at", "last_success_at", "is_enabled", "base_url", "user_id", "source_type"):
        op.drop_column("job_sources", column)
