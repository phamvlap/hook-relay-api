import uuid
from uuid import UUID

from sqlalchemy.orm import Mapped, mapped_column

from src.database.db import Base
from src.models.mixins import TimestampMixin


class BaseModel(TimestampMixin, Base):
    __abstract__ = True

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        nullable=False,
    )
