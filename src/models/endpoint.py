from uuid import UUID

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.enum import BaseStrEnum
from src.models.base import BaseModel
from src.models.delivery import WebhookDelivery


class WebhookEndpointStatus(BaseStrEnum):
    ACTIVE = "active"
    PAUSED = "paused"


class WebhookEndpoint(BaseModel):
    __tablename__ = "webhook_endpoints"

    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("owners.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[WebhookEndpointStatus] = mapped_column(
        SQLEnum(WebhookEndpointStatus, name="webhook_endpoint_status"),
        nullable=False,
        default=WebhookEndpointStatus.ACTIVE,
    )
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=5)

    # Relationships
    deliveries: Mapped[list[WebhookDelivery]] = relationship(
        "WebhookDelivery",
        back_populates="endpoint",
        cascade="all, delete-orphan",
    )
    owner = relationship("Owner", back_populates="endpoints")
