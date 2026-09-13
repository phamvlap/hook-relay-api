from enum import StrEnum

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import BaseModel


class WebhookEndpointStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"


class WebhookEndpoint(BaseModel):
    __tablename__ = "webhook_endpoints"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[WebhookEndpointStatus] = mapped_column(
        SQLEnum(WebhookEndpointStatus, name="webhook_endpoint_status"),
        nullable=False,
        default=WebhookEndpointStatus.ACTIVE,
    )
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=5)

    # Relationships
    deliveries = relationship(
        "WebhookDelivery",
        back_populates="endpoint",
        cascade="all, delete-orphan",
    )
