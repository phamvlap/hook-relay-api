from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from src.models.delivery import WebhookDeliveryStatus


class NestedEndpointForDeliveryListInEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    url: str


class DeliveryListInEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    endpoint: NestedEndpointForDeliveryListInEvent
    secret_version: str
    attempt: int
    status: WebhookDeliveryStatus
    status_code: int | None
    response_body: dict[str, Any] | None
    error_message: str | None
    duration_ms: int | None
    next_retry_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime
    updated_at: datetime


class NestedEndpointForDeliveryListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    url: str


class NestedEventForDeliveryListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_type: str


class DeliveryListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    endpoint: NestedEndpointForDeliveryListResponse
    event: NestedEventForDeliveryListResponse
    secret_version: str
    attempt: int
    status: WebhookDeliveryStatus
    status_code: int | None
    response_body: dict[str, Any] | None
    error_message: str | None
    duration_ms: int | None
    next_retry_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime
    updated_at: datetime


class NestedEndpointForDeliveryRetrieveResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    url: str


class NestedEventForDeliveryRetrieveResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_type: str
    payload: dict[str, Any]


class DeliveryRetrieveResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    endpoint: NestedEndpointForDeliveryRetrieveResponse
    event: NestedEventForDeliveryRetrieveResponse
    secret_version: str
    attempt: int
    status: WebhookDeliveryStatus
    status_code: int | None
    response_body: dict[str, Any] | None
    error_message: str | None
    duration_ms: int | None
    next_retry_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime
    updated_at: datetime
