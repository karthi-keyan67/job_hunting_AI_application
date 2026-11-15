from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


PlatformName = Literal["LINKEDIN", "NAUKRI", "INDEED", "INSTAHYRE", "CUTSHORT", "HIRIST"]


class AlertSourceUpdate(BaseModel):
    allowed_senders: list[str] = Field(min_length=1, max_length=50)
    required_terms: list[str] = Field(default_factory=list, max_length=50)
    label_ids: list[str] = Field(default_factory=list, max_length=20)


class DiscoveryUpdate(BaseModel):
    enabled: bool


class IntegrationAuditResponse(BaseModel):
    id: UUID
    platform: str
    action: str
    details: dict
    occurred_at: datetime
    source_id: UUID | None
