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
        return self.session.query(WebhookEndpoint).filter_by(id=id).first()
