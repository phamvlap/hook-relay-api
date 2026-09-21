from datetime import UTC, datetime

from sqlalchemy.orm import Session

from src.core.config import settings
from src.database.session import get_local_session
from src.models.endpoint import WebhookEndpoint, WebhookEndpointStatus


class EndpointRepository:
    def __init__(self, session: Session | None = None):
        if session is None:
            session = get_local_session(settings.postgres_dsn_str)
        self.session = session

    async def create(self, *, name: str, url: str, max_retries: int) -> WebhookEndpoint:
        endpoint = WebhookEndpoint(name=name, url=url, max_retries=max_retries)
        self.session.add(endpoint)
        self.session.commit()
        self.session.refresh(endpoint)
        return endpoint

    async def get_by_id(self, *, id: str) -> WebhookEndpoint | None:
        return self.session.query(WebhookEndpoint).filter_by(id=id, deleted_at=None).first()

    async def count(self) -> int:
        return self.session.query(WebhookEndpoint).filter_by(deleted_at=None).count()

    async def list(
        self,
        *,
        offset: int | None = None,
        limit: int | None = None,
        status: WebhookEndpointStatus | None = None,
    ) -> list[WebhookEndpoint]:
        query = self.session.query(WebhookEndpoint).filter_by(deleted_at=None)

        if status is not None:
            query = query.filter_by(status=status)

        query = query.order_by(WebhookEndpoint.created_at.desc())

        if offset is not None:
            query = query.offset(offset)

        if limit is not None:
            query = query.limit(limit)

        return query.all()

    async def update(
        self,
        *,
        endpoint: WebhookEndpoint,
        data: dict[str, str | int | None],
    ) -> WebhookEndpoint:
        for key, value in data.items():
            setattr(endpoint, key, value)

        self.session.flush()
        self.session.commit()
        self.session.refresh(endpoint)
        return endpoint

    async def soft_delete(self, *, endpoint: WebhookEndpoint) -> None:
        endpoint.deleted_at = datetime.now(tz=UTC)
        self.session.flush()
        self.session.commit()
