from sqlalchemy.orm import Mapped, relationship

from src.models.api_key import APIKey
from src.models.base import BaseModel


class Owner(BaseModel):
    __tablename__ = "owners"

    # Relationships
    api_keys: Mapped[list[APIKey]] = relationship(
        "APIKey",
        back_populates="owner",
        cascade="all, delete-orphan",
    )
    endpoints = relationship(
        "WebhookEndpoint",
        back_populates="owner",
        cascade="all, delete-orphan",
    )
    events = relationship(
        "WebhookEvent",
        back_populates="owner",
        cascade="all, delete-orphan",
    )
    deliveries = relationship(
        "WebhookDelivery",
        back_populates="owner",
        cascade="all, delete-orphan",
    )
