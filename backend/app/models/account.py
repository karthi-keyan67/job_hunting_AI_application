import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamped, UUIDPrimaryKey, json_array_type, json_object_type
from app.models.enums import ResumeParsingStatus


class User(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("length(email) >= 3", name="email_min_length"),)

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    profile: Mapped["UserProfile"] = relationship(back_populates="user", cascade="all, delete-orphan", uselist=False)
    preferences: Mapped["JobPreference"] = relationship(back_populates="user", cascade="all, delete-orphan", uselist=False)
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    resumes: Mapped[list["Resume"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    job_sources: Mapped[list["JobSource"]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    matches: Mapped[list["JobMatch"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    job_reviews: Mapped[list["JobReview"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    applications: Mapped[list["Application"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    automation_settings: Mapped["AutomationSettings | None"] = relationship(back_populates="user", cascade="all, delete-orphan", uselist=False)
    audit_logs: Mapped[list["ApplicationAuditLog"]] = relationship(back_populates="actor")
    interviews: Mapped[list["Interview"]] = relationship()
    follow_ups: Mapped[list["FollowUp"]] = relationship()


class UserProfile(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "user_profiles"
    __table_args__ = (
        CheckConstraint(
            "preferred_salary_minimum IS NULL OR preferred_salary_maximum IS NULL OR preferred_salary_minimum <= preferred_salary_maximum",
            name="salary_range",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(200))
    current_designation: Mapped[str | None] = mapped_column(String(200))
    current_company: Mapped[str | None] = mapped_column(String(200))
    total_experience_months: Mapped[int | None] = mapped_column(Integer)
    notice_period_days: Mapped[int | None] = mapped_column(Integer)
    preferred_salary_minimum: Mapped[float | None] = mapped_column(Numeric(12, 2))
    preferred_salary_maximum: Mapped[float | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR", server_default="INR", nullable=False)
    bio: Mapped[str | None] = mapped_column(Text)
    user: Mapped[User] = relationship(back_populates="profile")


class JobPreference(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "job_preferences"
    __table_args__ = (
        CheckConstraint(
            "minimum_experience_months IS NULL OR maximum_experience_months IS NULL OR minimum_experience_months <= maximum_experience_months",
            name="experience_range",
        ),
        CheckConstraint(
            "minimum_salary IS NULL OR maximum_salary IS NULL OR minimum_salary <= maximum_salary",
            name="salary_range",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    target_job_roles: Mapped[list[str]] = mapped_column(json_array_type(), default=list, nullable=False)
    required_skills: Mapped[list[str]] = mapped_column(json_array_type(), default=list, nullable=False)
    optional_skills: Mapped[list[str]] = mapped_column(json_array_type(), default=list, nullable=False)
    minimum_experience_months: Mapped[int | None] = mapped_column(Integer)
    maximum_experience_months: Mapped[int | None] = mapped_column(Integer)
    minimum_salary: Mapped[float | None] = mapped_column(Numeric(12, 2))
    maximum_salary: Mapped[float | None] = mapped_column(Numeric(12, 2))
    preferred_locations: Mapped[list[str]] = mapped_column(json_array_type(), default=list, nullable=False)
    work_modes: Mapped[list[str]] = mapped_column(json_array_type(), default=list, nullable=False)
    excluded_companies: Mapped[list[str]] = mapped_column(json_array_type(), default=list, nullable=False)
    excluded_roles: Mapped[list[str]] = mapped_column(json_array_type(), default=list, nullable=False)
    employment_types: Mapped[list[str]] = mapped_column(json_array_type(), default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    user: Mapped[User] = relationship(back_populates="preferences")


class Resume(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "resumes"
    __table_args__ = (
        Index(
            "uq_resumes_one_default_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("is_default IS TRUE"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    user: Mapped[User] = relationship(back_populates="resumes")
    versions: Mapped[list["ResumeVersion"]] = relationship(
        back_populates="resume",
        cascade="all, delete-orphan",
        order_by="ResumeVersion.version_number.desc()",
    )


class ResumeVersion(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "resume_versions"
    __table_args__ = (
        UniqueConstraint("resume_id", "version_number", name="uq_resume_versions_resume_version"),
        CheckConstraint("version_number > 0", name="version_number_positive"),
        CheckConstraint("file_size > 0", name="file_size_positive"),
        CheckConstraint("file_type IN ('PDF', 'DOCX', 'UNKNOWN')", name="file_type_supported"),
        Index("ix_resume_versions_resume_hash", "resume_id", "file_hash"),
    )

    resume_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_hash: Mapped[str | None] = mapped_column(String(64))
    parsing_status: Mapped[ResumeParsingStatus] = mapped_column(
        Enum(ResumeParsingStatus, name="resume_parsing_status"),
        default=ResumeParsingStatus.PENDING,
        nullable=False,
    )
    parsed_text: Mapped[str | None] = mapped_column(Text)
    parsed_data: Mapped[dict] = mapped_column(json_object_type(), default=dict, nullable=False)
    parsing_error: Mapped[str | None] = mapped_column(String(500))
    resume: Mapped[Resume] = relationship(back_populates="versions")


class RefreshToken(UUIDPrimaryKey, Timestamped, Base):
    """Stores only a digest of a signed refresh token to support rotation and revocation."""

    __tablename__ = "auth_refresh_tokens"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_auth_refresh_tokens_token_hash"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    family_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_hash: Mapped[str | None] = mapped_column(String(64))
    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class AuthLoginAttempt(UUIDPrimaryKey, Base):
    __tablename__ = "auth_login_attempts"
    __table_args__ = (
        UniqueConstraint("key_hash", name="uq_auth_login_attempts_key_hash"),
        CheckConstraint("attempts > 0", name="attempts_positive"),
        Index("ix_auth_login_attempts_window_started", "window_started"),
    )

    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    window_started: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
