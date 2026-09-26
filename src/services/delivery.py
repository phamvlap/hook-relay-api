import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

import httpx
from celery import Task
from fastapi import Request
from sqlalchemy.orm import Session

from src.core.pagination import PageNumberPaginationParams, PageNumberPaginationResponse
from src.exceptions.delivery import DeliveryNotFoundError
from src.models.delivery import WebhookDelivery, WebhookDeliveryStatus
from src.models.endpoint import WebhookEndpoint, WebhookEndpointSecret
from src.models.event import WebhookEvent
from src.repositories.delivery import DeliveryRepository
from src.repositories.endpoint import EndpointRepository, EndpointSecretRepository
from src.repositories.event import EventRepository
from src.schemas.delivery import DeliveryListInEvent, DeliveryListResponse, DeliveryRetrieveResponse
from src.tasks.webhook import deliver_webhook_task
from src.utils.endpoint import EndpointSecretCrypto


def _create_httpx_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, connect=5.0, read=10.0, write=10.0, pool=None),
        follow_redirects=True,
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )


class DeliveryService:
    def __init__(
        self,
        delivery_repository: DeliveryRepository,
        event_repository: EventRepository,
        endpoint_repository: EndpointRepository,
        endpoint_secret_repository: EndpointSecretRepository,
        session: Session,
        httpx_client: httpx.AsyncClient | None = None,
    ):
        self.delivery_repository = delivery_repository
        self.event_repository = event_repository
        self.endpoint_repository = endpoint_repository
        self.endpoint_secret_repository = endpoint_secret_repository
        self.session = session
        self.httpx_client = httpx_client or httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0, read=10.0, write=10.0, pool=None),
            follow_redirects=False,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )

    async def deliver(self, *, delivery_id: str | UUID) -> None:
        delivery = await self.delivery_repository.get_delivery_for_processing(
            delivery_id=delivery_id,
        )
        if not delivery or not delivery.endpoint or not delivery.event:
            return

        endpoint: WebhookEndpoint = delivery.endpoint
        event: WebhookEvent = delivery.event

        await self.delivery_repository.mark_as_delivering(delivery=delivery)
        self.session.commit()
        await self._sync_event_status(event_id=str(event.id))

        payload = {
            "id": str(event.id),
            "event_type": event.event_type,
            "data": event.payload,
            "timestamp": event.created_at.isoformat(),
        }
        payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "HookRelay/1.0",
            "X-Webhook-ID": str(event.id),
            "X-Webhook-Event-Type": event.event_type,
            "X-Webhook-Timestamp": event.created_at.isoformat(),
        }

        # Resolve signing secret for delivery.secret_version
        secret: WebhookEndpointSecret | None = None
        try:
            secret = await self.endpoint_secret_repository.get_by_version(
                endpoint_id=endpoint.id,
                version=delivery.secret_version,
            )
        except (ValueError, TypeError):
            pass

        if not secret:
            secret = await self.endpoint_secret_repository.get_active_secret(
                endpoint_id=endpoint.id,
            )

        endpoint_secret_crypto = EndpointSecretCrypto()

        if secret:
            raw_secret = endpoint_secret_crypto.decrypt(secret.encrypted_secret)
            current_timestamp = int(time.time())
            signature = endpoint_secret_crypto.compute_signature(
                payload=payload_bytes,
                secret=raw_secret,
                timestamp=current_timestamp,
            )
            headers["X-Webhook-Signature"] = (
                f"t={current_timestamp},v{delivery.secret_version}={signature}"
            )
            headers["X-Webhook-Secret-Version"] = str(delivery.secret_version)

        start_time = time.monotonic()

        try:
            async with self.httpx_client as client:
                response = await client.post(
                    endpoint.url,
                    content=payload_bytes,
                    headers=headers,
                )

            duration_ms = int((time.monotonic() - start_time) * 1000)

            if self._is_successful_status(response.status_code):
                await self.delivery_repository.mark_as_success(
                    delivery=delivery,
                    status_code=response.status_code,
                    response_body=self._get_response_body(response),
                    duration_ms=duration_ms,
                )

            elif self._should_retry(response.status_code):
                await self._process_retry_or_failure(
                    delivery=delivery,
                    error_message=f"HTTP {response.status_code}",
                    should_retry=True,
                    max_retries=endpoint.max_retries,
                    duration_ms=duration_ms,
                    status_code=response.status_code,
                )

            else:
                await self.delivery_repository.mark_as_failed(
                    delivery=delivery,
                    status_code=response.status_code,
                    response_body=self._get_response_body(response),
                    error_message=f"Received status code {response.status_code}",
                    duration_ms=duration_ms,
                )

        except httpx.InvalidURL as exc:
            await self.delivery_repository.mark_as_failed(
                delivery=delivery,
                status_code=None,
                error_message=str(exc),
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )

        except httpx.TimeoutException as exc:
            await self._process_retry_or_failure(
                delivery=delivery,
                error_message=str(exc),
                should_retry=True,
                max_retries=endpoint.max_retries,
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )

        except httpx.RequestError as exc:
            await self._process_retry_or_failure(
                delivery=delivery,
                error_message=str(exc),
                should_retry=True,
                max_retries=endpoint.max_retries,
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )

        finally:
            self.session.commit()
            await self._sync_event_status(event_id=str(event.id))

    def _is_successful_status(self, status_code: int) -> bool:
        return 200 <= status_code < 300

    def _should_retry(self, status_code: int) -> bool:
        return status_code in (408, 429) or (500 <= status_code < 600)

    def _get_response_body(self, response: httpx.Response) -> dict[str, Any] | None:
        try:
            return response.json()
        except (TypeError, ValueError):
            return None

    async def _sync_event_status(self, event_id: str) -> None:
        await self.event_repository.resolve_and_update_status(event_id=event_id)
        self.session.commit()

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
        event_id: str | UUID,
        owner_id: str | UUID,
        page_params: PageNumberPaginationParams,
    ) -> PageNumberPaginationResponse[DeliveryListInEvent]:
        total_count = await self.delivery_repository.count(event_id=event_id, owner_id=owner_id)
        items = await self.delivery_repository.list(
            event_id=event_id,
            owner_id=owner_id,
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

    async def list(
        self,
        *,
        owner_id: str | UUID,
        request: Request,
        page_params: PageNumberPaginationParams,
        event_id: str | None = None,
        endpoint_id: str | None = None,
        status: WebhookDeliveryStatus | None = None,
    ) -> PageNumberPaginationResponse[DeliveryListResponse]:
        total = await self.delivery_repository.count(
            owner_id=owner_id,
            event_id=event_id,
            endpoint_id=endpoint_id,
            status=status,
        )
        items = await self.delivery_repository.list(
            owner_id=owner_id,
            event_id=event_id,
            endpoint_id=endpoint_id,
            offset=page_params.offset,
            limit=page_params.limit,
            status=status,
        )

        return PageNumberPaginationResponse.build(
            request=request,
            total=total,
            page=page_params.page,
            page_size=page_params.page_size,
            items=[DeliveryListResponse.model_validate(item) for item in items],
        )

    async def retrieve(
        self,
        *,
        delivery_id: str | UUID,
        owner_id: str | UUID,
    ) -> DeliveryRetrieveResponse:
        delivery = await self.delivery_repository.get_by_id(id=delivery_id, owner_id=owner_id)
        if not delivery:
            raise DeliveryNotFoundError()

        return DeliveryRetrieveResponse.model_validate(delivery)
