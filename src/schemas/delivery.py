from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from src.models.delivery import WebhookDeliveryStatus


class DeliveryListInEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    endpoint_id: UUID
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
