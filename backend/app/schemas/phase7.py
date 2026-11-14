from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import FollowUpStatus, InterviewStatus


class InterviewCreate(BaseModel):
    application_id: UUID
    interview_type: str = Field(min_length=1, max_length=80)
    scheduled_at: datetime
    timezone: str = Field(default="Asia/Kolkata", max_length=80)
    meeting_url: str | None = Field(default=None, max_length=2000)
    interviewer_name: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=10000)

    @field_validator("scheduled_at")
    @classmethod
    def require_aware_time(cls, value: datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("scheduled_at must include a timezone offset")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown timezone") from exc
        return value

    @field_validator("meeting_url")
    @classmethod
    def safe_meeting_url(cls, value: str | None):
        if value is None or not value.strip():
            return None
        from urllib.parse import urlsplit
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Meeting URL must be a valid HTTP or HTTPS URL")
        return value


class InterviewUpdate(BaseModel):
    interview_type: str | None = Field(default=None, min_length=1, max_length=80)
    scheduled_at: datetime | None = None
    timezone: str | None = Field(default=None, max_length=80)
    meeting_url: str | None = Field(default=None, max_length=2000)
    interviewer_name: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=10000)
    status: InterviewStatus | None = None

    @model_validator(mode="after")
    def reject_null_required_updates(self):
        for name in ("interview_type", "scheduled_at", "timezone", "status"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self

    @field_validator("scheduled_at")
    @classmethod
    def aware_updated_time(cls, value: datetime | None):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("scheduled_at must include a timezone offset")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_updated_timezone(cls, value: str | None):
        if value is not None:
            try:
                ZoneInfo(value)
            except ZoneInfoNotFoundError as exc:
                raise ValueError("Unknown timezone") from exc
        return value

    @field_validator("meeting_url")
    @classmethod
    def safe_updated_meeting_url(cls, value: str | None):
        if value is None or not value.strip():
            return value
        from urllib.parse import urlsplit
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Meeting URL must be a valid HTTP or HTTPS URL")
        return value


class FollowUpCreate(BaseModel):
    application_id: UUID
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    due_at: datetime
    timezone: str = Field(default="Asia/Kolkata", max_length=80)

    @field_validator("due_at")
    @classmethod
    def require_aware_time(cls, value: datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("due_at must include a timezone offset")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown timezone") from exc
        return value


class FollowUpUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    due_at: datetime | None = None
    timezone: str | None = Field(default=None, max_length=80)
    status: FollowUpStatus | None = None

    @model_validator(mode="after")
    def reject_null_required_updates(self):
        for name in ("title", "due_at", "timezone", "status"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self

    @field_validator("due_at")
    @classmethod
    def aware_updated_due_time(cls, value: datetime | None):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("due_at must include a timezone offset")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_updated_timezone(cls, value: str | None):
        if value is not None:
            try:
                ZoneInfo(value)
            except ZoneInfoNotFoundError as exc:
                raise ValueError("Unknown timezone") from exc
        return value


class ApplicationNotesUpdate(BaseModel):
    notes: str | None = Field(default=None, max_length=20000)


class InterviewView(BaseModel):
    id: UUID
    user_id: UUID
    application_id: UUID
    interview_type: str
    scheduled_at: datetime
    timezone: str
    meeting_url: str | None
    interviewer_name: str | None
    notes: str | None
    status: InterviewStatus
    created_at: datetime
    updated_at: datetime


class FollowUpView(BaseModel):
    id: UUID
    user_id: UUID
    application_id: UUID
    title: str
    description: str | None
    due_at: datetime
    timezone: str
    status: FollowUpStatus
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
