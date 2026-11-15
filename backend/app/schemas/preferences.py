from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PreferencesUpdate(BaseModel):
    target_job_roles: list[str] = Field(default_factory=list, max_length=50)
    required_skills: list[str] = Field(default_factory=list, max_length=100)
    optional_skills: list[str] = Field(default_factory=list, max_length=100)
    minimum_experience_months: int | None = Field(default=None, ge=0, le=720)
    maximum_experience_months: int | None = Field(default=None, ge=0, le=720)
    minimum_salary: float | None = Field(default=None, ge=0)
    maximum_salary: float | None = Field(default=None, ge=0)
    preferred_locations: list[str] = Field(default_factory=list, max_length=100)
    work_modes: list[str] = Field(default_factory=list, max_length=10)
    excluded_companies: list[str] = Field(default_factory=list, max_length=100)
    excluded_roles: list[str] = Field(default_factory=list, max_length=100)
    employment_types: list[str] = Field(default_factory=list, max_length=20)
    is_active: bool = True

    @model_validator(mode="after")
    def ranges_are_valid(self):
        for minimum, maximum, label in (
            (self.minimum_experience_months, self.maximum_experience_months, "experience"),
            (self.minimum_salary, self.maximum_salary, "salary"),
        ):
            if minimum is not None and maximum is not None and minimum > maximum:
                raise ValueError(f"minimum {label} cannot exceed maximum")
        return self


class PreferencesResponse(PreferencesUpdate):
    model_config = ConfigDict(from_attributes=True)
    user_id: UUID
    created_at: datetime
    updated_at: datetime
