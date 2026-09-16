from typing import cast

from celery import Task

from src.models.endpoint import WebhookEndpointStatus
from src.repositories.delivery import DeliveryRepository
from src.repositories.endpoint import EndpointRepository
from src.repositories.event import EventRepository
from src.schemas.event import EventCreateRequest, EventCreateResponse
from src.tasks.webhook import deliver_webhook_task


class EventService:
    def __init__(
        self,
        event_repository: EventRepository,
        endpoint_repository: EndpointRepository,
        delivery_repository: DeliveryRepository,
    ):
        self.event_repository = event_repository
        self.endpoint_repository = endpoint_repository
        self.delivery_repository = delivery_repository

    async def create(self, data: EventCreateRequest) -> EventCreateResponse:
        event = await self.event_repository.create(
            event_type=data.event_type,
            payload=data.payload,
        )

        endpoints = await self.endpoint_repository.list(status=WebhookEndpointStatus.ACTIVE)

        deliveries_data = [
            {
                "event_id": str(event.id),
                "endpoint_id": str(endpoint.id),
            }
            for endpoint in endpoints
        ]
        deliveries = await self.delivery_repository.bulk_create(data=deliveries_data)

        task = cast(Task, deliver_webhook_task)
        for delivery in deliveries:
            task.delay(str(delivery.id))

        return EventCreateResponse.model_validate(event)
