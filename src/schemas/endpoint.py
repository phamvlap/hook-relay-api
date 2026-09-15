from datetime import datetime
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from src.models.endpoint import WebhookEndpointStatus


class EndpointCreateRequest(BaseModel):
    name: str = Field(..., max_length=255)
    url: AnyHttpUrl
    max_retries: int = Field(default=5, ge=0, le=20)


class EndpointCreateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    url: str
    status: WebhookEndpointStatus
    max_retries: int
    created_at: datetime


class EndpointRetrieveResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    url: str
    status: WebhookEndpointStatus
    max_retries: int
    created_at: datetime


class EndpointListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    url: str
    status: WebhookEndpointStatus
    max_retries: int
    created_at: datetime


class EndpointUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    url: AnyHttpUrl | None = Field(default=None)
    max_retries: int | None = Field(default=None, ge=0, le=20)


class EndpointUpdateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    url: str
    status: WebhookEndpointStatus
    max_retries: int
    created_at: datetime
