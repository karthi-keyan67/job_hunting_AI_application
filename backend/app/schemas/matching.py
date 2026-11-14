from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MatchingWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skills: float = Field(ge=0, le=100)
    experience: float = Field(ge=0, le=100)
    role: float = Field(ge=0, le=100)
    location: float = Field(ge=0, le=100)
    salary: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def weights_total_100(self):
        if round(sum(self.model_dump().values()), 6) != 100:
            raise ValueError("Matching weights must total 100")
        return self


class MatchingRunRequest(BaseModel):
    resume_version_id: UUID | None = None
    job_ids: list[UUID] | None = Field(default=None, max_length=100)
    include_ai: bool = False


class MatchResult(BaseModel):
    id: UUID
    job_id: UUID
    resume_version_id: UUID | None
    overall_score: float
    confidence: float
    eligibility_status: str
    skills_score: float | None
    experience_score: float | None
    role_score: float | None
    location_score: float | None
    salary_score: float | None
    ai_analysis: dict
    matched_skills: list[str]
    missing_required_skills: list[str]
    missing_preferred_skills: list[str]
    strengths: list[str]
    concerns: list[str]
    explanation: str
    model_name: str | None
    prompt_version: str
    scoring_version: str
    recommendation: str
    criteria_scores: dict[str, float | None]
    available_criteria: list[str]
    missing_criteria: list[str]
    job: dict
    created_at: datetime


class MatchingResults(BaseModel):
    items: list[MatchResult]
    total: int


class MatchingSummary(BaseModel):
    total: int
    average_score: float | None
    average_confidence: float | None
    eligibility: dict[str, int]
    recommendations: dict[str, int]
