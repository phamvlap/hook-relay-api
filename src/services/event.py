from typing import cast

from celery import Task
from fastapi import Request

from src.core.pagination import PageNumberPaginationParams, PageNumberPaginationResponse
from src.exceptions.event import EventNotFoundError
from src.models.endpoint import WebhookEndpointStatus
from src.repositories.delivery import DeliveryRepository
from src.repositories.endpoint import EndpointRepository
from src.repositories.event import EventRepository
from src.schemas.event import (
    EventCreateRequest,
    EventCreateResponse,
    EventListResponse,
    EventRetrieveResponse,
)
from src.tasks.webhook import deliver_webhook_task


class EventService:
    def __init__(
        self,
        event_repository: EventRepository | None = None,
        endpoint_repository: EndpointRepository | None = None,
        delivery_repository: DeliveryRepository | None = None,
    ):
        self.event_repository = event_repository or EventRepository()
        self.endpoint_repository = endpoint_repository or EndpointRepository()
        self.delivery_repository = delivery_repository or DeliveryRepository()

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

    async def retrieve(self, event_id: str) -> EventRetrieveResponse:
        event = await self.event_repository.get_by_id(id=event_id)
        if not event:
            raise EventNotFoundError()

        return EventRetrieveResponse.model_validate(event)

    async def list(
        self,
        request: Request,
        page_params: PageNumberPaginationParams,
    ) -> PageNumberPaginationResponse[EventListResponse]:
        total = await self.event_repository.count()
        events = await self.event_repository.list(
            offset=page_params.offset,
            limit=page_params.limit,
        )
        return PageNumberPaginationResponse.build(
            request=request,
            total=total,
            page=page_params.page,
            page_size=page_params.page_size,
            items=[EventListResponse.model_validate(event) for event in events],
        )
