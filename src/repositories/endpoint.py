from sqlalchemy.orm import Session

from src.models.endpoint import WebhookEndpoint


class EndpointRepository:
    def __init__(self, session: Session):
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

    async def list(self, *, offset: int = 0, limit: int = 10) -> list[WebhookEndpoint]:
        return (
            self.session.query(WebhookEndpoint)
            .filter_by(deleted_at=None)
            .order_by(WebhookEndpoint.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
