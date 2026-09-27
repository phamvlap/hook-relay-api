from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.enum import BaseStrEnum
from src.models.base import BaseModel


class WebhookDeliveryStatus(BaseStrEnum):
    QUEUED = "queued"
    DELIVERING = "delivering"
    SUCCESS = "success"
    RETRYING = "retrying"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class WebhookDelivery(BaseModel):
    __tablename__ = "webhook_deliveries"

    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("webhook_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    endpoint_id: Mapped[UUID] = mapped_column(
        ForeignKey("webhook_endpoints.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("owners.id", ondelete="CASCADE"),
        nullable=False,
    )

    # The version of the secret used for signing the webhook request. This is stored to ensure
    # that we can verify the signature of the request even if the secret has been rotated or revoked.
    secret_version: Mapped[int] = mapped_column(Integer, nullable=False)

    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[WebhookDeliveryStatus] = mapped_column(
        SQLEnum(WebhookDeliveryStatus, name="webhook_delivery_status"),
        nullable=False,
        default=WebhookDeliveryStatus.QUEUED,
    )
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    event = relationship("WebhookEvent", back_populates="deliveries")
    endpoint = relationship("WebhookEndpoint", back_populates="deliveries")
    owner = relationship("Owner", back_populates="deliveries")
    attempts: Mapped[list["WebhookDeliveryAttempt"]] = relationship(
        "WebhookDeliveryAttempt",
        back_populates="delivery",
        cascade="all, delete-orphan",
        order_by="WebhookDeliveryAttempt.attempt_number",
    )


class WebhookDeliveryAttempt(BaseModel):
    """
    Append-only immutable record representing an individual execution attempt
    of a webhook delivery.
    """

    __tablename__ = "webhook_delivery_attempts"

    delivery_id: Mapped[UUID] = mapped_column(
        ForeignKey("webhook_deliveries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)

    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_headers: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    response_headers: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    delivery = relationship("WebhookDelivery", back_populates="attempts")

    __table_args__ = (
        UniqueConstraint(
            "delivery_id",
            "attempt_number",
            name="uq_webhook_delivery_attempts_delivery_attempt",
        ),
    )
