from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=200)
    current_designation: str | None = Field(default=None, max_length=200)
    current_company: str | None = Field(default=None, max_length=200)
    total_experience_months: int | None = Field(default=None, ge=0, le=720)
    notice_period_days: int | None = Field(default=None, ge=0, le=3650)
    preferred_salary_minimum: float | None = Field(default=None, ge=0)
    preferred_salary_maximum: float | None = Field(default=None, ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3, pattern="^[A-Za-z]{3}$")
    bio: str | None = Field(default=None, max_length=10000)

    @model_validator(mode="after")
    def salary_range_is_valid(self):
        if self.preferred_salary_minimum is not None and self.preferred_salary_maximum is not None:
            if self.preferred_salary_minimum > self.preferred_salary_maximum:
                raise ValueError("preferred salary minimum cannot exceed maximum")
        return self


class ProfileResponse(ProfileUpdate):
    model_config = ConfigDict(from_attributes=True)
    user_id: UUID
