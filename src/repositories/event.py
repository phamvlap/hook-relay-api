from typing import Any

from sqlalchemy.orm import Session

from src.models.event import WebhookEvent


class EventRepository:
    def __init__(self, session: Session):
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

    async def list(self, *, offset: int = 0, limit: int = 10) -> list[WebhookEvent]:
        return (
            self.session.query(WebhookEvent)
            .filter_by(deleted_at=None)
            .order_by(WebhookEvent.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

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
