import time
from datetime import UTC, datetime, timedelta
from typing import cast

import httpx
from celery import Task
from fastapi import Request

from src.core.pagination import PageNumberPaginationParams, PageNumberPaginationResponse
from src.models.delivery import WebhookDelivery, WebhookDeliveryStatus
from src.repositories.delivery import DeliveryRepository
from src.repositories.endpoint import EndpointRepository
from src.repositories.event import EventRepository
from src.schemas.delivery import DeliveryListInEvent
from src.tasks.webhook import deliver_webhook_task


class DeliveryService:
    def __init__(
        self,
        delivery_repository: DeliveryRepository | None = None,
        event_repository: EventRepository | None = None,
        endpoint_repository: EndpointRepository | None = None,
    ):
        self.delivery_repository = delivery_repository or DeliveryRepository()
        self.event_repository = event_repository or EventRepository()
        self.endpoint_repository = endpoint_repository or EndpointRepository()

    async def deliver(self, delivery_id: str) -> None:
        delivery = await self.delivery_repository.get_by_id(id=delivery_id)
        if not delivery:
            return

        if delivery.status in [WebhookDeliveryStatus.SUCCESS, WebhookDeliveryStatus.DEAD_LETTER]:
            return

        event = await self.event_repository.get_by_id(id=str(delivery.event_id))
        endpoint = await self.endpoint_repository.get_by_id(id=str(delivery.endpoint_id))

        if not event or not endpoint:
            return

        await self.delivery_repository.mark_as_delivering(delivery=delivery)

        payload = {
            "id": str(event.id),
            "event_type": event.event_type,
            "data": event.payload,
            "timestamp": event.created_at.isoformat(),
        }
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-ID": str(event.id),
            "X-Webhook-Event-Type": event.event_type,
            "X-Webhook-Timestamp": event.created_at.isoformat(),
        }

        start_time = time.monotonic()

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    endpoint.url,
                    json=payload,
                    headers=headers,
                    timeout=10.0,
                )

            duration_ms = int((time.monotonic() - start_time) * 1000)

        except httpx.TimeoutException as exc:
            await self._process_retry_or_failure(
                delivery=delivery,
                error_message=str(exc),
                should_retry=True,
                max_retries=endpoint.max_retries,
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )
            return

        except httpx.RequestError as exc:
            await self._process_retry_or_failure(
                delivery=delivery,
                error_message=str(exc),
                should_retry=True,
                max_retries=endpoint.max_retries,
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )
            return

        if self._is_successful_status(response.status_code):
            await self.delivery_repository.mark_as_success(
                delivery=delivery,
                status_code=response.status_code,
                response_body=response.json(),
                duration_ms=duration_ms,
            )
            return

        if self._should_retry(response.status_code):
            await self._process_retry_or_failure(
                delivery=delivery,
                error_message=f"Received status code {response.status_code}",
                should_retry=True,
                max_retries=endpoint.max_retries,
                duration_ms=duration_ms,
                status_code=response.status_code,
            )
            return

        await self.delivery_repository.mark_as_failed(
            delivery=delivery,
            status_code=response.status_code,
            response_body=response.json(),
            error_message=f"Received status code {response.status_code}",
            duration_ms=duration_ms,
        )

    def _is_successful_status(self, status_code: int) -> bool:
        return 200 <= status_code < 300

    def _should_retry(self, status_code: int) -> bool:
        return status_code == 408 or status_code == 429 or (500 <= status_code < 600)

    async def _process_retry_or_failure(
        self,
        delivery: WebhookDelivery,
        *,
        error_message: str,
        should_retry: bool,
        max_retries: int,
        duration_ms: int,
        status_code: int | None = None,
    ) -> None:
        attempt = delivery.attempt + 1

        if not should_retry:
            await self.delivery_repository.mark_as_failed(
                delivery=delivery,
                status_code=status_code,
                error_message=error_message,
                duration_ms=duration_ms,
            )
            return

        if attempt >= max_retries:
            await self.delivery_repository.mark_as_dead_letter(
                delivery=delivery,
                attempt=attempt,
                status_code=status_code,
                error_message=error_message,
                duration_ms=duration_ms,
            )
            return

        retry_delay = self._compute_retry_delay(attempt)
        await self.delivery_repository.mark_as_retrying(
            delivery=delivery,
            attempt=attempt,
            status_code=status_code,
            error_message=error_message,
            duration_ms=duration_ms,
            next_retry_at=self._compute_next_retry_time(retry_delay),
        )

        task = cast(Task, deliver_webhook_task)
        task.apply_async(args=[str(delivery.id)], countdown=retry_delay)

    def _compute_retry_delay(self, attempt: int) -> float:
        base_delay = 2 ** (attempt - 1)
        jitter = base_delay * 0.1
        return base_delay + jitter

    def _compute_next_retry_time(self, delay: float) -> datetime:
        return datetime.now(UTC) + timedelta(seconds=delay)

    async def list_by_event(
        self,
        *,
        request: Request,
        event_id: str,
        page_params: PageNumberPaginationParams,
    ) -> PageNumberPaginationResponse[DeliveryListInEvent]:
        total_count = await self.delivery_repository.count(event_id=event_id)
        items = await self.delivery_repository.list(
            event_id=event_id,
            offset=page_params.offset,
            limit=page_params.limit,
        )

        return PageNumberPaginationResponse.build(
            request=request,
            total=total_count,
            page=page_params.page,
            page_size=page_params.page_size,
            items=[DeliveryListInEvent.model_validate(item) for item in items],
        )
