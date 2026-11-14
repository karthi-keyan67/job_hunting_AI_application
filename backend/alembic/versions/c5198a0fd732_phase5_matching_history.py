"""Add versioned job match history and matching preferences.

Revision ID: c5198a0fd732
Revises: b68e21c4a90f
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c5198a0fd732"
down_revision: Union[str, None] = "b68e21c4a90f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("job_preferences", sa.Column("excluded_roles", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column("job_preferences", sa.Column("employment_types", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False))

    op.drop_constraint("uq_job_matches_user_job", "job_matches", type_="unique")
    op.add_column("job_matches", sa.Column("resume_version_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("job_matches", sa.Column("input_fingerprint", sa.String(length=64), nullable=True))
    op.add_column("job_matches", sa.Column("overall_score", sa.Numeric(5, 2), server_default="0", nullable=False))
    op.execute("UPDATE job_matches SET overall_score = score")
    op.add_column("job_matches", sa.Column("confidence", sa.Numeric(5, 2), server_default="0", nullable=False))
    op.add_column("job_matches", sa.Column("eligibility_status", sa.String(length=20), server_default="UNKNOWN", nullable=False))
    for column in ("skills_score", "experience_score", "role_score", "location_score", "salary_score"):
        op.add_column("job_matches", sa.Column(column, sa.Numeric(5, 2), nullable=True))
    op.add_column("job_matches", sa.Column("ai_analysis", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False))
    for column in ("matched_skills", "missing_required_skills", "missing_preferred_skills", "strengths", "concerns"):
        op.add_column("job_matches", sa.Column(column, postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column("job_matches", sa.Column("explanation", sa.Text(), server_default="", nullable=False))
    op.add_column("job_matches", sa.Column("model_name", sa.String(length=120), nullable=True))
    op.add_column("job_matches", sa.Column("prompt_version", sa.String(length=40), server_default="phase5-v1", nullable=False))
    op.add_column("job_matches", sa.Column("scoring_version", sa.String(length=40), server_default="deterministic-v1", nullable=False))
    op.create_foreign_key("fk_job_matches_resume_version_id_resume_versions", "job_matches", "resume_versions", ["resume_version_id"], ["id"], ondelete="RESTRICT")
    op.create_unique_constraint("uq_job_matches_input_fingerprint", "job_matches", ["user_id", "job_id", "input_fingerprint"])
    op.create_index("ix_job_matches_user_id", "job_matches", ["user_id"])
    op.create_index("ix_job_matches_job_id", "job_matches", ["job_id"])
    op.create_index("ix_job_matches_overall_score", "job_matches", ["overall_score"])
    op.create_index("ix_job_matches_eligibility_status", "job_matches", ["eligibility_status"])
    op.create_check_constraint("ck_job_matches_overall_score_range", "job_matches", "overall_score >= 0 AND overall_score <= 100")
    op.create_check_constraint("ck_job_matches_confidence_range", "job_matches", "confidence >= 0 AND confidence <= 100")
    op.create_table(
        "matching_request_limits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("request_count > 0", name=op.f("ck_matching_request_limits_request_count_positive")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_matching_request_limits_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_matching_request_limits"),
        sa.UniqueConstraint("user_id", "window_started_at", name="uq_matching_request_limits_user_window"),
    )
    op.create_index("ix_matching_request_limits_window_started_at", "matching_request_limits", ["window_started_at"])


def downgrade() -> None:
    duplicates = op.get_bind().execute(sa.text("SELECT 1 FROM job_matches GROUP BY user_id, job_id HAVING count(*) > 1 LIMIT 1")).first()
    if duplicates:
        raise RuntimeError("Cannot downgrade Phase 5 while match history contains multiple versions for one user and job")
    op.drop_index("ix_matching_request_limits_window_started_at", table_name="matching_request_limits")
    op.drop_table("matching_request_limits")
    op.drop_constraint("ck_job_matches_confidence_range", "job_matches", type_="check")
    op.drop_constraint("ck_job_matches_overall_score_range", "job_matches", type_="check")
    op.drop_index("ix_job_matches_eligibility_status", table_name="job_matches")
    op.drop_index("ix_job_matches_overall_score", table_name="job_matches")
    op.drop_index("ix_job_matches_job_id", table_name="job_matches")
    op.drop_index("ix_job_matches_user_id", table_name="job_matches")
    op.drop_constraint("uq_job_matches_input_fingerprint", "job_matches", type_="unique")
    op.drop_constraint("fk_job_matches_resume_version_id_resume_versions", "job_matches", type_="foreignkey")
    for column in (
        "scoring_version", "prompt_version", "model_name", "explanation", "concerns", "strengths",
        "missing_preferred_skills", "missing_required_skills", "matched_skills", "ai_analysis",
        "salary_score", "location_score", "role_score", "experience_score", "skills_score",
        "eligibility_status", "confidence", "overall_score", "input_fingerprint", "resume_version_id",
    ):
        op.drop_column("job_matches", column)
    op.create_unique_constraint("uq_job_matches_user_job", "job_matches", ["user_id", "job_id"])
    op.drop_column("job_preferences", "excluded_roles")
    op.drop_column("job_preferences", "employment_types")
