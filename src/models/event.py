from typing import Any
from uuid import UUID

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.enum import BaseStrEnum
from src.models.base import BaseModel
from src.models.delivery import WebhookDelivery, WebhookDeliveryStatus


class WebhookEventStatus(BaseStrEnum):
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

    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Relationships
    deliveries: Mapped[list[WebhookDelivery]] = relationship(
        "WebhookDelivery",
        back_populates="event",
        cascade="all, delete-orphan",
    )
    owner = relationship("Owner", back_populates="events")

    __table_args__ = (
        Index(
            "uq_webhook_events_owner_id_idempotency_key",
            "owner_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL AND deleted_at IS NULL"),
        ),
    )


def resolve_event_status(
    delivery_status_counts: dict[WebhookDeliveryStatus, int],
) -> WebhookEventStatus:
    """
    Resolve the status of a webhook event based on the statuses of its deliveries.

    Args:
        delivery_status_counts (dict[WebhookDeliveryStatus, int]): A dictionary mapping delivery statuses to their counts.

    Returns:
        WebhookEventStatus: The resolved status of the webhook event.
    """
    total = sum(delivery_status_counts.values())
    if total == 0:
        return WebhookEventStatus.COMPLETED

    queued_count = delivery_status_counts.get(WebhookDeliveryStatus.QUEUED, 0)
    success_count = delivery_status_counts.get(WebhookDeliveryStatus.SUCCESS, 0)
    failure_count = delivery_status_counts.get(
        WebhookDeliveryStatus.FAILED, 0
    ) + delivery_status_counts.get(WebhookDeliveryStatus.DEAD_LETTER, 0)
    in_progress_count = delivery_status_counts.get(
        WebhookDeliveryStatus.DELIVERING, 0
    ) + delivery_status_counts.get(WebhookDeliveryStatus.RETRYING, 0)

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
