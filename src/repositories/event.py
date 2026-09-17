from typing import Any

from sqlalchemy.orm import Session

from src.core.config import settings
from src.database.session import get_local_session
from src.models.event import WebhookEvent


class EventRepository:
    def __init__(self, session: Session | None = None):
        if session is None:
            session = get_local_session(str(settings.postgres_dsn))
        self.session = session

    async def create(self, *, event_type: str, payload: dict[str, Any]) -> WebhookEvent:
        event = WebhookEvent(event_type=event_type, payload=payload)
        self.session.add(event)
        self.session.commit()
        self.session.refresh(event)
        return event

    async def get_by_id(self, *, id: str) -> WebhookEvent | None:
        return self.session.query(WebhookEvent).filter_by(id=id, deleted_at=None).first()

    async def count(self) -> int:
        return self.session.query(WebhookEvent).filter_by(deleted_at=None).count()

    async def list(
        self,
        *,
        offset: int | None = None,
        limit: int | None = None,
        status: str | None = None,
    ) -> list[WebhookEvent]:
        query = self.session.query(WebhookEvent).filter_by(deleted_at=None)

        if status is not None:
            query = query.filter_by(status=status)

        query = query.order_by(WebhookEvent.created_at.desc())

        if offset is not None:
            query = query.offset(offset)

        if limit is not None:
            query = query.limit(limit)

        return query.all()

    async def update(
        self,
        *,
        event: WebhookEvent,
        data: dict[str, str | int | None],
    ) -> WebhookEvent:
        for key, value in data.items():
            setattr(event, key, value)

        self.session.flush()
        self.session.commit()
        self.session.refresh(event)
        return event
