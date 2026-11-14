"""Add resume versioning and parsing metadata.

Revision ID: 83b5a91c2e47
Revises: c36174d281c7
Create Date: 2026-11-14
"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "83b5a91c2e47"
down_revision: Union[str, None] = "c36174d281c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

parsing_status_enum = postgresql.ENUM(
    "PENDING", "PROCESSING", "COMPLETED", "FAILED", "NEEDS_OCR",
    name="resume_parsing_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    op.add_column("resumes", sa.Column("title", sa.String(length=200), nullable=True))
    op.add_column(
        "resumes",
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.execute(
        sa.text(
            "UPDATE resumes SET title = COALESCE(NULLIF(left(original_filename, 200), ''), 'Resume')"
        )
    )
    op.execute(sa.text("UPDATE resumes SET is_default = false"))
    op.execute(
        sa.text(
            "WITH ranked AS ("
            " SELECT id, row_number() OVER (PARTITION BY user_id ORDER BY created_at, id) AS position"
            " FROM resumes WHERE is_primary IS TRUE"
            ") UPDATE resumes AS r SET is_default = true FROM ranked"
            " WHERE r.id = ranked.id AND ranked.position = 1"
        )
    )
    op.alter_column("resumes", "title", nullable=False)

    parsing_status_enum.create(bind, checkfirst=True)
    op.create_table(
        "resume_versions",
        sa.Column("resume_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("file_type", sa.String(length=10), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=True),
        sa.Column("parsing_status", parsing_status_enum, nullable=False),
        sa.Column("parsed_text", sa.Text(), nullable=True),
        sa.Column(
            "parsed_data",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("parsing_error", sa.String(length=500), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("version_number > 0", name=op.f("ck_resume_versions_version_number_positive")),
        sa.CheckConstraint("file_size > 0", name=op.f("ck_resume_versions_file_size_positive")),
        sa.CheckConstraint("file_type IN ('PDF', 'DOCX', 'UNKNOWN')", name=op.f("ck_resume_versions_file_type_supported")),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], name=op.f("fk_resume_versions_resume_id_resumes"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resume_versions")),
        sa.UniqueConstraint("resume_id", "version_number", name="uq_resume_versions_resume_version"),
        sa.UniqueConstraint("storage_key", name="uq_resume_versions_storage_key"),
    )
    op.create_index("ix_resume_versions_resume_hash", "resume_versions", ["resume_id", "file_hash"])

    # Preserve existing Phase 2 file records as version 1 before removing the old columns.
    legacy_rows = bind.execute(
        sa.text(
            "SELECT id, original_filename, storage_key, content_type, file_size_bytes, created_at, updated_at"
            " FROM resumes"
        )
    ).mappings()
    for row in legacy_rows:
        filename = row["original_filename"] or "legacy-resume"
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        mime = (row["content_type"] or "").lower()
        file_type = "PDF" if extension == "pdf" or mime == "application/pdf" else (
            "DOCX" if extension == "docx" or "wordprocessingml" in mime else "UNKNOWN"
        )
        bind.execute(
            sa.text(
                "INSERT INTO resume_versions "
                "(id, resume_id, version_number, original_filename, storage_key, file_type, file_size, "
                "file_hash, parsing_status, parsed_data, created_at, updated_at) "
                "VALUES (:id, :resume_id, 1, :filename, :storage_key, :file_type, :file_size, NULL, "
                "'PENDING', CAST('{}' AS JSONB), :created_at, :updated_at)"
            ),
            {
                "id": uuid.uuid4(),
                "resume_id": row["id"],
                "filename": filename[:255],
                "storage_key": row["storage_key"],
                "file_type": file_type,
                "file_size": row["file_size_bytes"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        )

    op.create_index(
        "uq_resumes_one_default_per_user",
        "resumes",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_default IS TRUE"),
    )
    op.drop_constraint("uq_resumes_user_storage_key", "resumes", type_="unique")
    op.drop_constraint(op.f("ck_resumes_file_size_positive"), "resumes", type_="check")
    op.drop_column("resumes", "original_filename")
    op.drop_column("resumes", "storage_key")
    op.drop_column("resumes", "content_type")
    op.drop_column("resumes", "file_size_bytes")
    op.drop_column("resumes", "is_primary")


def downgrade() -> None:
    bind = op.get_bind()
    resume_count = bind.execute(sa.text("SELECT count(*) FROM resumes")).scalar_one()
    version_count = bind.execute(sa.text("SELECT count(*) FROM resume_versions")).scalar_one()
    if resume_count or version_count:
        raise RuntimeError(
            "Refusing to downgrade resume versioning while resume records exist; "
            "the Phase 2 schema cannot represent multiple versions without data loss."
        )

    op.drop_index("uq_resumes_one_default_per_user", table_name="resumes")
    op.drop_index("ix_resume_versions_resume_hash", table_name="resume_versions")
    op.drop_table("resume_versions")
    parsing_status_enum.drop(bind, checkfirst=True)

    op.add_column("resumes", sa.Column("original_filename", sa.String(length=255), nullable=False))
    op.add_column("resumes", sa.Column("storage_key", sa.String(length=500), nullable=False))
    op.add_column("resumes", sa.Column("content_type", sa.String(length=120), nullable=False))
    op.add_column("resumes", sa.Column("file_size_bytes", sa.Integer(), nullable=False))
    op.add_column("resumes", sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.create_check_constraint(op.f("ck_resumes_file_size_positive"), "resumes", "file_size_bytes > 0")
    op.create_unique_constraint("uq_resumes_user_storage_key", "resumes", ["user_id", "storage_key"])
    op.drop_column("resumes", "title")
    op.drop_column("resumes", "is_default")
