from collections import Counter
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import BaseModel
from src.models.delivery import WebhookDelivery, WebhookDeliveryStatus


class WebhookEventStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    PARTIALLY_FAILED = "partially_failed"
    FAILED = "failed"


class WebhookEvent(BaseModel):
    __tablename__ = "webhook_events"

    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("owners.id", ondelete="CASCADE"),
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[WebhookEventStatus] = mapped_column(
        SQLEnum(WebhookEventStatus, name="webhook_event_status"),
        nullable=False,
        default=WebhookEventStatus.QUEUED,
    )

    # Relationships
    deliveries: Mapped[list[WebhookDelivery]] = relationship(
        "WebhookDelivery",
        back_populates="event",
        cascade="all, delete-orphan",
    )
    owner = relationship("Owner", back_populates="events")


def resolve_event_status(delivery_statuses: list[WebhookDeliveryStatus]) -> WebhookEventStatus:
    """
    Resolve the status of a webhook event based on the statuses of its deliveries.

    Args:
        delivery_statuses (list[WebhookDeliveryStatus]): A list of delivery statuses.

    Returns:
        WebhookEventStatus: The resolved status of the webhook event.
    """
    if not delivery_statuses:
        return WebhookEventStatus.COMPLETED

    status_counts = Counter(delivery_statuses)
    total = len(delivery_statuses)

    success_count = status_counts[WebhookDeliveryStatus.SUCCESS]
    failure_count = (
        status_counts[WebhookDeliveryStatus.FAILED]
        + status_counts[WebhookDeliveryStatus.DEAD_LETTER]
    )
    in_progress_count = (
        status_counts[WebhookDeliveryStatus.DELIVERING]
        + status_counts[WebhookDeliveryStatus.RETRYING]
    )
    queued_count = status_counts[WebhookDeliveryStatus.QUEUED]

    if queued_count == total:
        return WebhookEventStatus.QUEUED

    if in_progress_count > 0 or (queued_count > 0 and (success_count + failure_count > 0)):
        return WebhookEventStatus.PROCESSING

    if success_count + failure_count == total:
        if failure_count == 0:
            return WebhookEventStatus.COMPLETED

        if success_count == 0:
            return WebhookEventStatus.FAILED

        return WebhookEventStatus.PARTIALLY_FAILED

    return WebhookEventStatus.PROCESSING
