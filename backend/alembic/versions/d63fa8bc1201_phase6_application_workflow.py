"""Add human-approved application preparation workflow.

Revision ID: d63fa8bc1201
Revises: c5198a0fd732
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "d63fa8bc1201"
down_revision: Union[str, None] = "c5198a0fd732"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

draft_type = postgresql.ENUM("TAILORED_RESUME", "COVER_LETTER", "RECRUITER_MESSAGE", "APPLICATION_ANSWERS", name="application_draft_type", create_type=False)
draft_status = postgresql.ENUM("GENERATED", "EDITED", "APPROVED", "SUPERSEDED", name="application_draft_status", create_type=False)


def upgrade() -> None:
    op.execute("ALTER TYPE job_review_status ADD VALUE IF NOT EXISTS 'PENDING_REVIEW'")
    op.execute("ALTER TYPE job_review_status ADD VALUE IF NOT EXISTS 'APPROVED_FOR_PREPARATION'")
    draft_type.create(op.get_bind(), checkfirst=True)
    draft_status.create(op.get_bind(), checkfirst=True)

    op.add_column("job_reviews", sa.Column("rejection_reason", sa.Text(), nullable=True))
    op.add_column("job_reviews", sa.Column("match_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_job_reviews_match_id_job_matches", "job_reviews", "job_matches", ["match_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_job_reviews_user_status", "job_reviews", ["user_id", "status"])
    op.create_table(
        "job_review_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_review_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["job_review_id"], ["job_reviews.id"], ondelete="CASCADE", name="fk_job_review_events_job_review_id_job_reviews"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_job_review_events_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_job_review_events"),
    )
    op.create_index("ix_job_review_events_review_created", "job_review_events", ["job_review_id", "created_at"])

    op.add_column("applications", sa.Column("resume_version_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("applications", sa.Column("job_match_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("applications", sa.Column("job_review_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_applications_resume_version_id_resume_versions", "applications", "resume_versions", ["resume_version_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_applications_job_match_id_job_matches", "applications", "job_matches", ["job_match_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_applications_job_review_id_job_reviews", "applications", "job_reviews", ["job_review_id"], ["id"], ondelete="SET NULL")

    op.drop_constraint("uq_application_drafts_application_version", "application_drafts", type_="unique")
    op.add_column("application_drafts", sa.Column("body", sa.Text(), server_default="", nullable=False))
    op.add_column("application_drafts", sa.Column("draft_type", draft_type, server_default="COVER_LETTER", nullable=False))
    op.add_column("application_drafts", sa.Column("status", draft_status, server_default="GENERATED", nullable=False))
    op.add_column("application_drafts", sa.Column("generated_by", sa.String(length=40), server_default="AI", nullable=False))
    op.add_column("application_drafts", sa.Column("generation_model", sa.String(length=120), nullable=True))
    op.add_column("application_drafts", sa.Column("prompt_version", sa.String(length=40), server_default="phase6-v1", nullable=False))
    op.add_column("application_drafts", sa.Column("evidence", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.create_unique_constraint("uq_application_drafts_app_type_version", "application_drafts", ["application_id", "draft_type", "version"])
    op.create_index("ix_application_drafts_app_type_created", "application_drafts", ["application_id", "draft_type", "created_at"])

    op.add_column("application_approvals", sa.Column("approver_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("application_approvals", sa.Column("draft_version_ids", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column("application_approvals", sa.Column("checklist_snapshot", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.create_foreign_key("fk_application_approvals_approver_user_id_users", "application_approvals", "users", ["approver_user_id"], ["id"], ondelete="SET NULL")
    op.add_column("application_audit_logs", sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.create_index("ix_application_audit_logs_occurred_at", "application_audit_logs", ["occurred_at"])
    op.alter_column("application_audit_logs", "application_id", nullable=True)
    op.drop_constraint("fk_application_audit_logs_application_id_applications", "application_audit_logs", type_="foreignkey")
    op.create_foreign_key("fk_application_audit_logs_application_id_applications", "application_audit_logs", "applications", ["application_id"], ["id"], ondelete="RESTRICT")
    op.drop_constraint("fk_application_audit_logs_actor_user_id_users", "application_audit_logs", type_="foreignkey")
    op.create_foreign_key("fk_application_audit_logs_actor_user_id_users", "application_audit_logs", "users", ["actor_user_id"], ["id"], ondelete="RESTRICT")
    op.add_column("application_audit_logs", sa.Column("job_review_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_application_audit_logs_job_review_id_job_reviews", "application_audit_logs", "job_reviews", ["job_review_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_application_audit_logs_job_review_id", "application_audit_logs", ["job_review_id"])
    op.execute("""
        CREATE FUNCTION prevent_application_audit_mutation() RETURNS trigger AS $$
        BEGIN
            IF current_setting('app.audit_cleanup', true) = 'on' THEN
                IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'application audit logs are append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER application_audit_append_only
        BEFORE UPDATE OR DELETE ON application_audit_logs
        FOR EACH ROW EXECUTE FUNCTION prevent_application_audit_mutation();
    """)


def downgrade() -> None:
    has_unassociated_logs = op.get_bind().execute(sa.text("SELECT 1 FROM application_audit_logs WHERE application_id IS NULL LIMIT 1")).first()
    if has_unassociated_logs:
        raise RuntimeError("Cannot downgrade Phase 6 while job-review audit events have no application association")
    op.execute("DROP TRIGGER IF EXISTS application_audit_append_only ON application_audit_logs")
    op.execute("DROP FUNCTION IF EXISTS prevent_application_audit_mutation()")
    op.drop_index("ix_application_audit_logs_job_review_id", table_name="application_audit_logs")
    op.drop_constraint("fk_application_audit_logs_job_review_id_job_reviews", "application_audit_logs", type_="foreignkey")
    op.drop_column("application_audit_logs", "job_review_id")
    op.drop_constraint("fk_application_audit_logs_actor_user_id_users", "application_audit_logs", type_="foreignkey")
    op.create_foreign_key("fk_application_audit_logs_actor_user_id_users", "application_audit_logs", "users", ["actor_user_id"], ["id"], ondelete="SET NULL")
    op.drop_constraint("fk_application_audit_logs_application_id_applications", "application_audit_logs", type_="foreignkey")
    op.create_foreign_key("fk_application_audit_logs_application_id_applications", "application_audit_logs", "applications", ["application_id"], ["id"], ondelete="CASCADE")
    op.alter_column("application_audit_logs", "application_id", nullable=False)
    op.drop_index("ix_application_audit_logs_occurred_at", table_name="application_audit_logs")
    op.drop_column("application_audit_logs", "occurred_at")
    op.drop_constraint("fk_application_approvals_approver_user_id_users", "application_approvals", type_="foreignkey")
    op.drop_column("application_approvals", "checklist_snapshot")
    op.drop_column("application_approvals", "draft_version_ids")
    op.drop_column("application_approvals", "approver_user_id")
    op.drop_index("ix_application_drafts_app_type_created", table_name="application_drafts")
    op.drop_constraint("uq_application_drafts_app_type_version", "application_drafts", type_="unique")
    for name in ("evidence", "prompt_version", "generation_model", "generated_by", "status", "draft_type", "body"):
        op.drop_column("application_drafts", name)
    op.create_unique_constraint("uq_application_drafts_application_version", "application_drafts", ["application_id", "version"])
    op.drop_constraint("fk_applications_job_review_id_job_reviews", "applications", type_="foreignkey")
    op.drop_constraint("fk_applications_job_match_id_job_matches", "applications", type_="foreignkey")
    op.drop_constraint("fk_applications_resume_version_id_resume_versions", "applications", type_="foreignkey")
    for name in ("job_review_id", "job_match_id", "resume_version_id"):
        op.drop_column("applications", name)
    op.drop_index("ix_job_review_events_review_created", table_name="job_review_events")
    op.drop_table("job_review_events")
    op.drop_index("ix_job_reviews_user_status", table_name="job_reviews")
    op.drop_constraint("fk_job_reviews_match_id_job_matches", "job_reviews", type_="foreignkey")
    op.drop_column("job_reviews", "match_id")
    op.drop_column("job_reviews", "rejection_reason")
    draft_status.drop(op.get_bind(), checkfirst=True)
    draft_type.drop(op.get_bind(), checkfirst=True)
    # PostgreSQL enum values added above are intentionally retained: removing labels is not supported safely.
