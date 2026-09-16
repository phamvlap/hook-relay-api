from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.models.event import WebhookEventStatus


class EventCreateRequest(BaseModel):
    event_type: str = Field(..., max_length=255)
    payload: dict[str, Any] = Field(default_factory=dict)


class EventCreateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_type: str
    payload: dict[str, Any]
    status: WebhookEventStatus
    created_at: datetime
    updated_at: datetime
