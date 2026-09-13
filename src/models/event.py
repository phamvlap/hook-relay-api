from enum import StrEnum
from typing import Any

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import BaseModel


class WebhookEventStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class WebhookEvent(BaseModel):
    __tablename__ = "webhook_events"

    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[WebhookEventStatus] = mapped_column(
        SQLEnum(WebhookEventStatus, name="webhook_event_status"),
        nullable=False,
        default=WebhookEventStatus.QUEUED,
    )

    # Relationships
    deliveries = relationship(
        "WebhookDelivery",
        back_populates="event",
        cascade="all, delete-orphan",
    )
