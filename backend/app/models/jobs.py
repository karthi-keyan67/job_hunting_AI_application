import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from app.models.base import Base, Timestamped, UUIDPrimaryKey, json_object_type
from app.models.enums import JobSourceStatus, ReviewStatus, RunStatus


class JobSource(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "job_sources"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), default="CAREER_PAGE", nullable=False)
    connector_type: Mapped[str] = mapped_column(String(80), default="CAREER_PAGE", nullable=False)
    status: Mapped[JobSourceStatus] = mapped_column(Enum(JobSourceStatus, name="job_source_status"), default=JobSourceStatus.DISABLED, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    base_url: Mapped[str | None] = mapped_column(Text)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    configuration: Mapped[dict] = mapped_column(json_object_type(), default=dict, nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner: Mapped["User | None"] = relationship(back_populates="job_sources")
    jobs: Mapped[list["Job"]] = relationship(back_populates="source")
    collection_runs: Mapped[list["CollectionRun"]] = relationship(back_populates="source")


class Job(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_jobs_source_external_id"),
        Index("ix_jobs_company_title", "company_name", "title"),
        Index("ix_jobs_expires_at", "expires_at"),
        Index("ix_jobs_status_last_seen", "status", "last_seen_at"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job_sources.id", ondelete="RESTRICT"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(300), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    company_name: Mapped[str] = mapped_column(String(300), nullable=False)
    location: Mapped[str | None] = mapped_column(String(300))
    work_mode: Mapped[str | None] = mapped_column(String(40))
    employment_type: Mapped[str | None] = mapped_column(String(40))
    salary_min: Mapped[float | None] = mapped_column(Numeric(12, 2))
    salary_max: Mapped[float | None] = mapped_column(Numeric(12, 2))
    legacy_salary_minimum: Mapped[float | None] = mapped_column("salary_minimum", Numeric(12, 2))
    legacy_salary_maximum: Mapped[float | None] = mapped_column("salary_maximum", Numeric(12, 2))
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    salary_period: Mapped[str | None] = mapped_column(String(16))
    salary_minimum = synonym("legacy_salary_minimum")
    salary_maximum = synonym("legacy_salary_maximum")
    experience_min: Mapped[int | None] = mapped_column()
    experience_max: Mapped[int | None] = mapped_column()
    legacy_experience_minimum_months: Mapped[int | None] = mapped_column("experience_minimum_months")
    legacy_experience_maximum_months: Mapped[int | None] = mapped_column("experience_maximum_months")
    experience_minimum_months = synonym("legacy_experience_minimum_months")
    experience_maximum_months = synonym("legacy_experience_maximum_months")
    description: Mapped[str] = mapped_column(Text, nullable=False)
    job_url: Mapped[str | None] = mapped_column(Text)
    apply_url: Mapped[str | None] = mapped_column(Text)
    legacy_application_url: Mapped[str | None] = mapped_column("application_url", Text)
    application_url = synonym("legacy_application_url")
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    raw_data: Mapped[dict] = mapped_column(json_object_type(), default=dict, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(json_object_type(), default=dict, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", server_default="ACTIVE", nullable=False)
    source: Mapped[JobSource] = relationship(back_populates="jobs")
    skills: Mapped[list["JobSkill"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    matches: Mapped[list["JobMatch"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    reviews: Mapped[list["JobReview"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    applications: Mapped[list["Application"]] = relationship(back_populates="job")


class JobSkill(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "job_skills"
    __table_args__ = (
        UniqueConstraint("job_id", "skill", name="uq_job_skills_job_skill"),
        UniqueConstraint("job_id", "skill_name", "skill_type", name="uq_job_skills_job_skill_name_type"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    skill_name: Mapped[str] = mapped_column(String(120), nullable=False)
    skill: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    skill_type: Mapped[str] = mapped_column(String(20), default="REQUIRED", server_default="REQUIRED", nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    job: Mapped[Job] = relationship(back_populates="skills")


class JobMatch(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "job_matches"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_job_matches_user_job"),
        Index("ix_job_matches_score", "score"),
        CheckConstraint("score >= 0 AND score <= 100", name="score_range"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    details: Mapped[dict] = mapped_column(json_object_type(), default=dict, nullable=False)
    user: Mapped["User"] = relationship(back_populates="matches")
    job: Mapped[Job] = relationship(back_populates="matches")


class JobReview(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "job_reviews"
    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_job_reviews_user_job"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[ReviewStatus] = mapped_column(Enum(ReviewStatus, name="job_review_status"), default=ReviewStatus.PENDING, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    user: Mapped["User"] = relationship(back_populates="job_reviews")
    job: Mapped[Job] = relationship(back_populates="reviews")


class CollectionRun(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "collection_runs"
    __table_args__ = (
        Index("ix_collection_runs_status_started", "status", "started_at"),
        Index("uq_collection_runs_one_running_per_source", "source_id", unique=True, postgresql_where=text("status = 'RUNNING'")),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job_sources.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus, name="collection_run_status"), default=RunStatus.RUNNING, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_metadata: Mapped[dict] = mapped_column("metadata", json_object_type(), default=dict, nullable=False)
    metadata_json = synonym("run_metadata")
    statistics: Mapped[dict] = mapped_column(json_object_type(), default=dict, nullable=False)
    jobs_found: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    jobs_created: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    jobs_updated: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    jobs_skipped: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    error_summary: Mapped[str | None] = mapped_column(Text)
    source: Mapped[JobSource] = relationship(back_populates="collection_runs")


class JobDuplicate(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "job_duplicates"
    __table_args__ = (
        UniqueConstraint("job_id", "duplicate_job_id", name="uq_job_duplicates_pair"),
        CheckConstraint("job_id <> duplicate_job_id", name="jobs_must_differ"),
        Index("ix_job_duplicates_duplicate_job_id", "duplicate_job_id"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    duplicate_job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    match_reason: Mapped[dict] = mapped_column(json_object_type(), default=dict, nullable=False)
