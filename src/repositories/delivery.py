from sqlalchemy.orm import Session

from src.models.delivery import WebhookDelivery


class DeliveryRepository:
    def __init__(self, session: Session):
        self.session = session

    async def create(
        self,
        *,
        event_id: str,
        endpoint_id: str,
    ) -> WebhookDelivery:
        delivery = WebhookDelivery(event_id=event_id, endpoint_id=endpoint_id)
        self.session.add(delivery)
        self.session.commit()
        self.session.refresh(delivery)
        return delivery

    async def bulk_create(self, *, data: list[dict[str, str]]) -> list[WebhookDelivery]:
        deliveries: list[WebhookDelivery] = []
        for item in data:
            delivery = WebhookDelivery(**item)
            deliveries.append(delivery)

        self.session.add_all(deliveries)
        self.session.commit()

        for delivery in deliveries:
            self.session.refresh(delivery)

        return deliveries

    async def get_by_id(self, *, id: str) -> WebhookDelivery | None:
        return self.session.query(WebhookDelivery).filter_by(id=id, deleted_at=None).first()

    async def count(self) -> int:
        return self.session.query(WebhookDelivery).filter_by(deleted_at=None).count()

    async def list(self, *, offset: int = 0, limit: int = 10) -> list[WebhookDelivery]:
        return (
            self.session.query(WebhookDelivery)
            .filter_by(deleted_at=None)
            .order_by(WebhookDelivery.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    async def update(
        self,
        *,
        delivery: WebhookDelivery,
        data: dict[str, str | int | None],
    ) -> WebhookDelivery:
        for key, value in data.items():
            setattr(delivery, key, value)

        self.session.flush()
        self.session.commit()
        self.session.refresh(delivery)
        return delivery
