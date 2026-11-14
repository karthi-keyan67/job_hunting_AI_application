from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NormalizedJob(BaseModel):
    external_id: str | None = Field(default=None, max_length=300)
    source_id: UUID
    source_name: str
    title: str
    company_name: str
    description: str = ""
    employment_type: str | None = None
    experience_min: int | None = Field(default=None, ge=0, le=720)
    experience_max: int | None = Field(default=None, ge=0, le=720)
    location: str | None = None
    work_mode: str | None = None
    salary_min: Decimal | None = Field(default=None, ge=0)
    salary_max: Decimal | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, min_length=3, max_length=3)
    salary_period: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    job_url: str | None = None
    apply_url: str | None = None
    posted_at: datetime | None = None
    expires_at: datetime | None = None
    raw_data: dict = Field(default_factory=dict)
    content_hash: str | None = None

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.experience_min is not None and self.experience_max is not None and self.experience_min > self.experience_max:
            raise ValueError("Minimum experience cannot exceed maximum experience")
        if self.salary_min is not None and self.salary_max is not None and self.salary_min > self.salary_max:
            raise ValueError("Minimum salary cannot exceed maximum salary")
        return self


class JobSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    source_type: str = Field(min_length=1, max_length=80)
    base_url: str | None = None
    configuration: dict = Field(default_factory=dict)
    is_enabled: bool = False


class JobSourcePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: str | None = None
    configuration: dict | None = None
    is_enabled: bool | None = None


class JobSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    source_type: str
    base_url: str | None
    is_enabled: bool
    configuration: dict
    last_success_at: datetime | None
    last_failure_at: datetime | None
    created_at: datetime
    updated_at: datetime
    integration_status: str


class CollectionRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    source_id: UUID
    started_at: datetime
    completed_at: datetime | None
    status: str
    jobs_found: int
    jobs_created: int
    jobs_updated: int
    jobs_skipped: int
    duration_seconds: float | None = None
    retry_count: int = 0
    matching_duration_seconds: float | None = None
    matching_failed: bool = False
    error_message: str | None
    run_metadata: dict = Field(serialization_alias="metadata")


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    source_id: UUID
    source_name: str
    external_id: str
    title: str
    company_name: str
    description: str
    employment_type: str | None
    experience_min: int | None
    experience_max: int | None
    location: str | None
    work_mode: str | None
    salary_min: Decimal | None
    salary_max: Decimal | None
    salary_currency: str | None
    salary_period: str | None
    job_url: str | None
    apply_url: str | None
    posted_at: datetime | None
    expires_at: datetime | None
    content_hash: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    status: str
    required_skills: list[str]
    preferred_skills: list[str]
    possible_duplicate: bool
    created_at: datetime


class JobImport(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    company_name: str = Field(min_length=1, max_length=300)
    location: str | None = Field(default=None, max_length=300)
    description: str = Field(default="", max_length=100_000)
    job_url: str | None = Field(default=None, max_length=2048)
    apply_url: str | None = Field(default=None, max_length=2048)
    work_mode: str | None = None
    employment_type: str | None = None
    experience_min: int | None = Field(default=None, ge=0, le=720)
    experience_max: int | None = Field(default=None, ge=0, le=720)
    salary_min: Decimal | None = Field(default=None, ge=0)
    salary_max: Decimal | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, min_length=3, max_length=3)
    salary_period: str | None = None
    required_skills: list[str] = Field(default_factory=list, max_length=100)
    preferred_skills: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.experience_min is not None and self.experience_max is not None and self.experience_min > self.experience_max:
            raise ValueError("Minimum experience cannot exceed maximum experience")
        if self.salary_min is not None and self.salary_max is not None and self.salary_min > self.salary_max:
            raise ValueError("Minimum salary cannot exceed maximum salary")
        return self


class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int
