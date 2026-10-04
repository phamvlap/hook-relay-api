import time
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import httpx
import orjson
from celery import Task
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.pagination import PageNumberPaginationParams, PageNumberPaginationResponse
from src.core.retry import RetryPolicy, webhook_delivery_policy
from src.exceptions.delivery import DeliveryNotEligibleForRetryError, DeliveryNotFoundError
from src.models.delivery import WebhookDelivery, WebhookDeliveryStatus
from src.models.endpoint import (
    WebhookEndpoint,
    WebhookEndpointSecret,
    WebhookEndpointStatus,
)
from src.models.event import WebhookEvent
from src.repositories.delivery import DeliveryAttemptRepository, DeliveryRepository
from src.repositories.endpoint import EndpointRepository, EndpointSecretRepository
from src.repositories.event import EventRepository
from src.schemas.delivery import (
    DeliveryAttemptListResponse,
    DeliveryListInEvent,
    DeliveryListResponse,
    DeliveryRetrieveResponse,
    DeliveryRetryResponse,
)
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
        delivery_attempt_repository: DeliveryAttemptRepository,
        event_repository: EventRepository,
        endpoint_repository: EndpointRepository,
        endpoint_secret_repository: EndpointSecretRepository,
        session: AsyncSession,
        httpx_client: httpx.AsyncClient | None = None,
        retry_policy: RetryPolicy | None = None,
    ):
        self.delivery_repository = delivery_repository
        self.delivery_attempt_repository = delivery_attempt_repository
        self.event_repository = event_repository
        self.endpoint_repository = endpoint_repository
        self.endpoint_secret_repository = endpoint_secret_repository
        self.session = session
        self.httpx_client = httpx_client or httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0, read=10.0, write=10.0, pool=None),
            follow_redirects=False,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
        self.retry_policy = retry_policy or webhook_delivery_policy

    async def deliver(self, *, delivery_id: str | UUID) -> None:
        delivery = await self.delivery_repository.get_delivery_for_processing(
            delivery_id=delivery_id,
        )
        if (
            not delivery
            or not delivery.endpoint
            or delivery.endpoint.deleted_at is not None
            or not delivery.event
        ):
            return

        if delivery.endpoint.status != WebhookEndpointStatus.ACTIVE:
            return

        endpoint: WebhookEndpoint = delivery.endpoint
        event: WebhookEvent = delivery.event

        await self.delivery_repository.mark_as_delivering(delivery=delivery)
        await self.session.commit()
        await self._sync_event_status(event_id=str(event.id))

        payload = {
            "id": str(event.id),
            "event_type": event.event_type,
            "data": event.payload,
            "timestamp": event.created_at.isoformat(),
        }
        payload_bytes = orjson.dumps(payload)

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

        current_attempt_num = delivery.attempt
        started_at = datetime.now(tz=UTC)
        start_time = time.monotonic()
        sanitized_headers = self._sanitize_request_headers(headers)

        try:
            async with self.httpx_client as client:
                response = await client.post(
                    endpoint.url,
                    content=payload_bytes,
                    headers=headers,
                )

            completed_at = datetime.now(tz=UTC)
            duration_ms = int((time.monotonic() - start_time) * 1000)
            response_body = self._get_response_body(response)
            response_headers = dict(response.headers)

            if self._is_successful_status(response.status_code):
                await self.delivery_attempt_repository.create(
                    delivery_id=delivery.id,
                    attempt_number=current_attempt_num,
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_ms=duration_ms,
                    status_code=response.status_code,
                    request_headers=sanitized_headers,
                    response_headers=response_headers,
                    response_body=response_body,
                )
                await self.delivery_repository.mark_as_success(
                    delivery=delivery,
                    status_code=response.status_code,
                    response_body=response_body,
                    duration_ms=duration_ms,
                )

            elif self.retry_policy.should_retry(
                current_retry_count=delivery.retry_count,
                status_code=response.status_code,
                custom_max_retries=endpoint.max_retries,
            ):
                error_message = f"HTTP {response.status_code}"
                await self.delivery_attempt_repository.create(
                    delivery_id=delivery.id,
                    attempt_number=current_attempt_num,
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_ms=duration_ms,
                    status_code=response.status_code,
                    request_headers=sanitized_headers,
                    response_headers=response_headers,
                    response_body=response_body,
                    error_message=error_message,
                )
                await self._process_retry_or_failure(
                    delivery=delivery,
                    error_message=error_message,
                    should_retry=True,
                    max_retries=endpoint.max_retries,
                    duration_ms=duration_ms,
                    status_code=response.status_code,
                    response_headers=response_headers,
                )

            else:
                error_message = f"Received status code {response.status_code}"
                await self.delivery_attempt_repository.create(
                    delivery_id=delivery.id,
                    attempt_number=current_attempt_num,
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_ms=duration_ms,
                    status_code=response.status_code,
                    request_headers=sanitized_headers,
                    response_headers=response_headers,
                    response_body=response_body,
                    error_message=error_message,
                )
                await self.delivery_repository.mark_as_failed(
                    delivery=delivery,
                    status_code=response.status_code,
                    response_body=response_body,
                    error_message=error_message,
                    duration_ms=duration_ms,
                )

        except httpx.InvalidURL as exc:
            completed_at = datetime.now(tz=UTC)
            duration_ms = int((time.monotonic() - start_time) * 1000)
            await self.delivery_attempt_repository.create(
                delivery_id=delivery.id,
                attempt_number=current_attempt_num,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
                status_code=None,
                request_headers=sanitized_headers,
                error_message=str(exc),
            )
            await self.delivery_repository.mark_as_failed(
                delivery=delivery,
                status_code=None,
                error_message=str(exc),
                duration_ms=duration_ms,
            )

        except (httpx.TimeoutException, httpx.RequestError) as exc:
            completed_at = datetime.now(tz=UTC)
            duration_ms = int((time.monotonic() - start_time) * 1000)
            await self.delivery_attempt_repository.create(
                delivery_id=delivery.id,
                attempt_number=current_attempt_num,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
                status_code=None,
                request_headers=sanitized_headers,
                error_message=str(exc),
            )
            await self._process_retry_or_failure(
                delivery=delivery,
                error_message=str(exc),
                should_retry=True,
                max_retries=endpoint.max_retries,
                duration_ms=duration_ms,
                status_code=None,
            )

        finally:
            await self.session.commit()
            await self._sync_event_status(event_id=str(event.id))

    def _sanitize_request_headers(self, headers: dict[str, str]) -> dict[str, str]:
        sanitized = dict(headers)
        for key in list(sanitized.keys()):
            if key.lower() in ("authorization", "cookie", "proxy-authorization"):
                sanitized[key] = "[REDACTED]"
        return sanitized

    def _is_successful_status(self, status_code: int) -> bool:
        return 200 <= status_code < 300

    def _get_response_body(
        self,
        response: httpx.Response,
        max_bytes: int = 65536,
    ) -> dict[str, Any] | None:
        try:
            if len(response.content) > max_bytes:
                return {
                    "_truncated": True,
                    "preview": response.text[:1024],
                    "content_length": len(response.content),
                }
            return response.json()
        except (TypeError, ValueError):
            if response.text:
                return {"raw": response.text[:1024]}
            return None

    async def _sync_event_status(self, event_id: str) -> None:
        updated = await self.event_repository.resolve_and_update_status(event_id=event_id)
        if updated:
            await self.session.commit()

    async def _process_retry_or_failure(
        self,
        delivery: WebhookDelivery,
        *,
        error_message: str,
        should_retry: bool,
        max_retries: int,
        duration_ms: int,
        status_code: int | None = None,
        response_headers: dict[str, str] | None = None,
    ) -> None:
        if not should_retry:
            await self.delivery_repository.mark_as_failed(
                delivery=delivery,
                status_code=status_code,
                error_message=error_message,
                duration_ms=duration_ms,
            )
            return

        next_retry_count = delivery.retry_count + 1
        next_attempt = delivery.attempt + 1

        if not self.retry_policy.should_retry(
            current_retry_count=delivery.retry_count,
            status_code=status_code,
            custom_max_retries=max_retries,
        ):
            if next_retry_count >= max_retries:
                await self.delivery_repository.mark_as_dead_letter(
                    delivery=delivery,
                    attempt=next_attempt,
                    retry_count=next_retry_count,
                    status_code=status_code,
                    error_message=error_message,
                    duration_ms=duration_ms,
                )
            else:
                await self.delivery_repository.mark_as_failed(
                    delivery=delivery,
                    status_code=status_code,
                    error_message=error_message,
                    duration_ms=duration_ms,
                )
            return

        retry_delay = self.retry_policy.compute_delay(
            retry_count=delivery.retry_count,
            status_code=status_code,
            headers=response_headers,
        )
        await self.delivery_repository.mark_as_retrying(
            delivery=delivery,
            attempt=next_attempt,
            retry_count=next_retry_count,
            status_code=status_code,
            error_message=error_message,
            duration_ms=duration_ms,
            next_retry_at=self.retry_policy.compute_next_retry_time(delay_seconds=retry_delay),
        )

        task = cast(Task, deliver_webhook_task)
        task.apply_async(args=[str(delivery.id)], countdown=retry_delay)

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

    async def list_attempts(
        self,
        *,
        request: Request,
        delivery_id: str | UUID,
        owner_id: str | UUID,
        page_params: PageNumberPaginationParams,
    ) -> PageNumberPaginationResponse[DeliveryAttemptListResponse]:
        delivery = await self.delivery_repository.get_by_id(id=delivery_id, owner_id=owner_id)
        if not delivery:
            raise DeliveryNotFoundError()

        total = await self.delivery_attempt_repository.count_by_delivery_id(delivery_id=delivery.id)
        items = await self.delivery_attempt_repository.list_by_delivery_id(
            delivery_id=delivery.id,
            offset=page_params.offset,
            limit=page_params.limit,
        )

        return PageNumberPaginationResponse.build(
            request=request,
            total=total,
            page=page_params.page,
            page_size=page_params.page_size,
            items=[DeliveryAttemptListResponse.model_validate(item) for item in items],
        )

    async def retry(
        self,
        *,
        delivery_id: str | UUID,
        owner_id: str | UUID,
    ) -> DeliveryRetryResponse:
        delivery = await self.delivery_repository.get_by_id_for_update(
            delivery_id=delivery_id,
            owner_id=owner_id,
        )
        if not delivery:
            raise DeliveryNotFoundError()

        if delivery.status != WebhookDeliveryStatus.DEAD_LETTER:
            raise DeliveryNotEligibleForRetryError(
                f"Delivery is in '{delivery.status}' status. Only 'dead_letter' deliveries can be manually retried."
            )

        if (
            not delivery.endpoint
            or delivery.endpoint.deleted_at is not None
            or delivery.endpoint.status != WebhookEndpointStatus.ACTIVE
        ):
            raise DeliveryNotEligibleForRetryError("Associated endpoint is inactive or not found.")

        try:
            async with self.session.begin_nested():
                await self.delivery_repository.mark_as_queued_for_retry(delivery=delivery)
                await self._sync_event_status(event_id=str(delivery.event_id))

            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        task = cast(Task, deliver_webhook_task)
        task.delay(str(delivery.id))

        return DeliveryRetryResponse(success=True)
