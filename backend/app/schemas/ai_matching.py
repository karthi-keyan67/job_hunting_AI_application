from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["resume", "job"]
    quote: str = Field(min_length=1, max_length=500)


class TransferableSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_skill: str = Field(min_length=1, max_length=120)
    job_skill: str = Field(min_length=1, max_length=120)
    evidence: Evidence


class AISkillAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    matched: list[str] = Field(default_factory=list, max_length=50)
    missing_required: list[str] = Field(default_factory=list, max_length=50)
    missing_preferred: list[str] = Field(default_factory=list, max_length=50)
    transferable: list[TransferableSkill] = Field(default_factory=list, max_length=30)


class AIExperienceAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["MATCH", "PARTIAL_MATCH", "MISMATCH", "UNKNOWN"]
    explanation: str = Field(max_length=1000)


class SemanticMatchAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role_relevance: int = Field(ge=0, le=100)
    skill_analysis: AISkillAnalysis
    experience_analysis: AIExperienceAnalysis
    strengths: list[str] = Field(default_factory=list, max_length=20)
    concerns: list[str] = Field(default_factory=list, max_length=20)
    recommendation: Literal["APPLY", "REVIEW", "SKIP"]
    explanation: str = Field(max_length=2000)
    evidence: list[Evidence] = Field(default_factory=list, max_length=30)
