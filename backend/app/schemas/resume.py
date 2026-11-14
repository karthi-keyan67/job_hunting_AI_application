from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ResumeVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    version_number: int
    original_filename: str
    file_type: str
    file_size: int
    file_hash: str | None
    parsing_status: str
    parsed_text: str | None
    parsed_data: dict
    parsing_error: str | None
    created_at: datetime


class ResumeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    is_default: bool
    created_at: datetime
    updated_at: datetime
    versions: list[ResumeVersionResponse]


class ResumeSummary(BaseModel):
    id: UUID
    title: str
    is_default: bool
    version_count: int
    latest_version: ResumeVersionResponse | None
    created_at: datetime
    updated_at: datetime
