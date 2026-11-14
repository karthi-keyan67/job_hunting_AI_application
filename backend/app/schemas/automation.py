from datetime import datetime, time
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AutomationSettingsUpdate(BaseModel):
    enabled: bool = True
    timezone: str = "Asia/Kolkata"
    email_enabled: bool = False
    notify_job_matches: bool = True
    notify_collection: bool = True
    notify_reminders: bool = True
    minimum_match_score: int = Field(default=75, ge=0, le=100)
    quiet_start: str | None = None
    quiet_end: str | None = None
    reminder_intervals_minutes: list[int] = Field(default_factory=lambda: [1440, 60], max_length=5)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return value

    @field_validator("quiet_start", "quiet_end")
    @classmethod
    def valid_clock(cls, value):
        if value is not None:
            try:
                time.fromisoformat(value)
            except ValueError as exc:
                raise ValueError("Time must use HH:MM format") from exc
        return value

    @field_validator("reminder_intervals_minutes")
    @classmethod
    def valid_intervals(cls, value):
        if any(item < 5 or item > 10080 for item in value) or len(set(value)) != len(value):
            raise ValueError("Reminder intervals must be unique values between 5 and 10080 minutes")
        return sorted(value, reverse=True)

    @model_validator(mode="after")
    def paired_quiet_hours(self):
        if bool(self.quiet_start) != bool(self.quiet_end):
            raise ValueError("Both quiet_start and quiet_end are required together")
        return self


class AutomationSettingsView(AutomationSettingsUpdate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


class NotificationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    notification_type: str
    payload: dict
    is_read: bool
    delivery_status: str
    delivery_attempts: int
    delivered_at: datetime | None
    created_at: datetime


class ManualCollectionRequest(BaseModel):
    source_ids: list[UUID] = Field(default_factory=list, max_length=20)
