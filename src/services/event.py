from typing import cast
from uuid import UUID

from celery import Task
from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.pagination import PageNumberPaginationParams, PageNumberPaginationResponse
from src.exceptions.event import EventConflictError, EventNotFoundError
from src.models.delivery import WebhookDelivery
from src.models.endpoint import WebhookEndpointStatus
from src.models.event import WebhookEventStatus
from src.repositories.delivery import DeliveryRepository
from src.repositories.endpoint import EndpointRepository, EndpointSecretRepository
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
        endpoint_secret_repository: EndpointSecretRepository,
        session: AsyncSession,
    ) -> None:
        self.event_repository = event_repository
        self.endpoint_repository = endpoint_repository
        self.endpoint_secret_repository = endpoint_secret_repository
        self.delivery_repository = delivery_repository
        self.session = session

    async def create(
        self,
        *,
        data: EventCreateRequest,
        idempotency_key: str | None = None,
        owner_id: str | UUID,
    ) -> EventCreateResponse:
        if idempotency_key:
            # Check if an event with the same idempotency key already exists
            existing_event = await self.event_repository.get_by_idempotency_key(
                idempotency_key=idempotency_key,
                owner_id=owner_id,
            )
            if existing_event:
                return EventCreateResponse.model_validate(existing_event)

        deliveries: list[WebhookDelivery] = []

        try:
            async with self.session.begin_nested():
                # Get all active endpoints for the owner
                endpoints = await self.endpoint_repository.list(
                    owner_id=owner_id,
                    status=WebhookEndpointStatus.ACTIVE,
                )

                initial_event_status = (
                    WebhookEventStatus.COMPLETED if not endpoints else WebhookEventStatus.QUEUED
                )

                # Create the webhook event
                event = await self.event_repository.create(
                    event_type=data.event_type,
                    payload=data.payload,
                    idempotency_key=idempotency_key,
                    owner_id=owner_id,
                    status=initial_event_status,
                )

                if endpoints:
                    # Create a delivery for each active endpoint
                    for endpoint in endpoints:
                        active_secret = await self.endpoint_secret_repository.get_active_secret(
                            endpoint_id=endpoint.id,
                        )
                        secret_version = active_secret.version if active_secret else 1

                        delivery = WebhookDelivery(
                            event_id=event.id,
                            endpoint_id=endpoint.id,
                            owner_id=owner_id,
                            secret_version=secret_version,
                        )
                        deliveries.append(delivery)

                    await self.delivery_repository.bulk_create(deliveries=deliveries)

            # Commit the transaction
            await self.session.commit()

        except IntegrityError:
            await self.session.rollback()

            # If concurrently creating an event with the same idempotency key, check if it already exists
            if idempotency_key:
                existing_event = await self.event_repository.get_by_idempotency_key(
                    idempotency_key=idempotency_key,
                    owner_id=owner_id,
                )
                if existing_event:
                    return EventCreateResponse.model_validate(existing_event)

            raise EventConflictError()

        except Exception:
            await self.session.rollback()
            raise

        if deliveries:
            # Trigger the Celery task to deliver the webhook for each delivery
            task = cast(Task, deliver_webhook_task)
            for delivery in deliveries:
                task.delay(str(delivery.id))

        return EventCreateResponse.model_validate(event)

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
