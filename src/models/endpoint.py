from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.enum import BaseStrEnum
from src.models.base import BaseModel
from src.models.delivery import WebhookDelivery


class WebhookEndpointStatus(BaseStrEnum):
    ACTIVE = "active"
    PAUSED = "paused"


class WebhookEndpointSecretStatus(BaseStrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


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
    secrets: Mapped[list["WebhookEndpointSecret"]] = relationship(
        "WebhookEndpointSecret",
        back_populates="endpoint",
        cascade="all, delete-orphan",
    )
    owner = relationship("Owner", back_populates="endpoints")

    __table_args__ = (
        Index(
            "uq_webhook_endpoints_owner_id_url",
            "owner_id",
            "url",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class WebhookEndpointSecret(BaseModel):
    __tablename__ = "webhook_endpoint_secrets"

    endpoint_id: Mapped[UUID] = mapped_column(
        ForeignKey("webhook_endpoints.id", ondelete="CASCADE"),
        nullable=False,
    )

    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[WebhookEndpointSecretStatus] = mapped_column(
        SQLEnum(WebhookEndpointSecretStatus, name="webhook_endpoint_secret_status"),
        nullable=False,
        default=WebhookEndpointSecretStatus.ACTIVE,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Optional timestamp for when the secret was revoked
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    endpoint = relationship("WebhookEndpoint", back_populates="secrets")

    __table_args__ = (
        Index(
            "uq_webhook_endpoint_secrets_endpoint_id_version",
            "endpoint_id",
            "version",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
