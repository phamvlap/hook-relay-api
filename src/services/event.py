from typing import cast
from uuid import UUID

from celery import Task
from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.core.pagination import PageNumberPaginationParams, PageNumberPaginationResponse
from src.exceptions.event import EventNotFoundError
from src.models.delivery import WebhookDelivery
from src.models.endpoint import WebhookEndpointStatus
from src.models.event import WebhookEventStatus
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
        event_repository: EventRepository,
        endpoint_repository: EndpointRepository,
        delivery_repository: DeliveryRepository,
        session: Session,
    ) -> None:
        self.event_repository = event_repository
        self.endpoint_repository = endpoint_repository
        self.delivery_repository = delivery_repository
        self.session = session

    async def create(
        self,
        *,
        data: EventCreateRequest,
        owner_id: str | UUID,
    ) -> EventCreateResponse:
        try:
            event = await self.event_repository.create(
                event_type=data.event_type,
                payload=data.payload,
                owner_id=owner_id,
            )

            endpoints = await self.endpoint_repository.list(
                owner_id=owner_id,
                status=WebhookEndpointStatus.ACTIVE,
            )

            if not endpoints:
                await self.event_repository.update(
                    event=event,
                    data={"status": WebhookEventStatus.COMPLETED},
                )
                self.session.commit()
                return EventCreateResponse.model_validate(event)

            deliveries: list[WebhookDelivery] = []
            for endpoint in endpoints:
                delivery = WebhookDelivery(
                    event_id=event.id,
                    endpoint_id=endpoint.id,
                    owner_id=owner_id,
                )
                deliveries.append(delivery)

            await self.delivery_repository.bulk_create(deliveries=deliveries)

            self.session.commit()

            task = cast(Task, deliver_webhook_task)
            for delivery in deliveries:
                task.delay(str(delivery.id))

            return EventCreateResponse.model_validate(event)

        except IntegrityError:
            self.session.rollback()
            raise

        except Exception:
            self.session.rollback()
            raise

    async def retrieve(
        self,
        *,
        event_id: str | UUID,
        owner_id: str | UUID,
    ) -> EventRetrieveResponse:
        event = await self.event_repository.get_by_id(id=event_id, owner_id=owner_id)
        if not event:
            raise EventNotFoundError()

        return EventRetrieveResponse.model_validate(event)

    async def list(
        self,
        owner_id: str | UUID,
        request: Request,
        page_params: PageNumberPaginationParams,
        status: WebhookEventStatus | None = None,
    ) -> PageNumberPaginationResponse[EventListResponse]:
        total = await self.event_repository.count(owner_id=owner_id, status=status)
        events = await self.event_repository.list(
            owner_id=owner_id,
            offset=page_params.offset,
            limit=page_params.limit,
            status=status,
        )

        return PageNumberPaginationResponse.build(
            request=request,
            total=total,
            page=page_params.page,
            page_size=page_params.page_size,
            items=[EventListResponse.model_validate(event) for event in events],
        )
