from datetime import datetime
from typing import Any
from uuid import UUID

import orjson
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.exceptions.event import EventValidationError
from src.models.event import WebhookEventStatus

_MAX_PAYLOAD_SIZE = 1024 * 1024  # 1 MB


class EventCreateRequest(BaseModel):
    event_type: str = Field(..., min_length=1, max_length=255)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise EventValidationError("Event type cannot be empty or whitespace")
        return trimmed

    @field_validator("payload")
    @classmethod
    def validate_payload_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        serialized = orjson.dumps(value, default=str)
        if len(serialized) > _MAX_PAYLOAD_SIZE:
            raise EventValidationError(f"Payload size cannot exceed {_MAX_PAYLOAD_SIZE} bytes")
        return value


class EventCreateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_type: str
    payload: dict[str, Any]
    status: WebhookEventStatus
    created_at: datetime
    updated_at: datetime


class EventListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_type: str
    payload: dict[str, Any]
    status: WebhookEventStatus
    created_at: datetime
    updated_at: datetime


class EventRetrieveResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_type: str
    payload: dict[str, Any]
    status: WebhookEventStatus
    created_at: datetime
    updated_at: datetime
