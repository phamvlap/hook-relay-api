from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.enum import BaseStrEnum
from src.models.base import BaseModel


class APIKeyStatus(BaseStrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class APIKeyEnvironment(BaseStrEnum):
    TEST = "test"
    LIVE = "live"


class APIKey(BaseModel):
    __tablename__ = "api_keys"

    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("owners.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    key_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    status: Mapped[APIKeyStatus] = mapped_column(
        SQLEnum(APIKeyStatus, name="api_key_status"),
        nullable=False,
        default=APIKeyStatus.ACTIVE,
    )
    environment: Mapped[APIKeyEnvironment] = mapped_column(
        SQLEnum(APIKeyEnvironment, name="api_key_environment"),
        nullable=False,
        default=APIKeyEnvironment.TEST,
    )

    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    owner = relationship("Owner", back_populates="api_keys")
