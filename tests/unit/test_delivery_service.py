"""Unit tests for DeliveryService covering:
1. Stuck Delivery Reaper (reap_stuck_deliveries & reap_stuck_deliveries_task)
2. Race condition prevention (Post-commit Celery task dispatch vs DB rollback)
3. Retry eligibility and state transitions
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from src.core.retry import RetryPolicy
from src.core.ssrf import SSRFSecurityError
from src.models.delivery import WebhookDelivery, WebhookDeliveryStatus
from src.models.endpoint import WebhookEndpoint, WebhookEndpointStatus
from src.models.event import WebhookEvent, WebhookEventStatus
from src.services.delivery import DeliveryService
from src.tasks.webhook import reap_stuck_deliveries_task


def _create_mock_delivery(
    *,
    status: WebhookDeliveryStatus = WebhookDeliveryStatus.DELIVERING,
    attempt: int = 1,
    retry_count: int = 0,
    max_retries: int = 3,
    endpoint_status: WebhookEndpointStatus = WebhookEndpointStatus.ACTIVE,
    updated_at: datetime | None = None,
) -> WebhookDelivery:
    endpoint = MagicMock(spec=WebhookEndpoint)
    endpoint.id = uuid4()
    endpoint.url = "https://example.com/webhook"
    endpoint.status = endpoint_status
    endpoint.max_retries = max_retries
    endpoint.deleted_at = None

    event = MagicMock(spec=WebhookEvent)
    event.id = uuid4()
    event.event_type = "user.created"
    event.payload = {"user_id": 123}
    event.status = WebhookEventStatus.PROCESSING
    event.created_at = datetime.now(tz=UTC)
    event.deleted_at = None

    delivery = MagicMock(spec=WebhookDelivery)
    delivery.id = uuid4()
    delivery.event_id = event.id
    delivery.endpoint_id = endpoint.id
    delivery.owner_id = uuid4()
    delivery.secret_version = 1
    delivery.status = status
    delivery.attempt = attempt
    delivery.retry_count = retry_count
    delivery.manual_retry_count = 0
    delivery.next_retry_at = None
    delivery.updated_at = updated_at or (datetime.now(tz=UTC) - timedelta(minutes=10))
    delivery.created_at = datetime.now(tz=UTC) - timedelta(minutes=10)
    delivery.deleted_at = None
    delivery.endpoint = endpoint
    delivery.event = event

    return delivery


@pytest.fixture
def mock_deps():
    mock_delivery_repo = AsyncMock()
    mock_attempt_repo = AsyncMock()
    mock_event_repo = AsyncMock()
    mock_endpoint_repo = AsyncMock()
    mock_secret_repo = AsyncMock()
    mock_session = AsyncMock()
    mock_http_client = AsyncMock(spec=httpx.AsyncClient)
    mock_retry_policy = MagicMock(spec=RetryPolicy)

    # Defaults
    mock_retry_policy.should_retry.return_value = True
    mock_retry_policy.compute_delay.return_value = 10
    mock_retry_policy.compute_next_retry_time.return_value = datetime.now(tz=UTC) + timedelta(
        seconds=10
    )
    mock_event_repo.resolve_and_update_status.return_value = True

    service = DeliveryService(
        delivery_repository=mock_delivery_repo,
        delivery_attempt_repository=mock_attempt_repo,
        event_repository=mock_event_repo,
        endpoint_repository=mock_endpoint_repo,
        endpoint_secret_repository=mock_secret_repo,
        session=mock_session,
        httpx_client=mock_http_client,
        retry_policy=mock_retry_policy,
    )

    return {
        "service": service,
        "delivery_repo": mock_delivery_repo,
        "attempt_repo": mock_attempt_repo,
        "event_repo": mock_event_repo,
        "endpoint_repo": mock_endpoint_repo,
        "secret_repo": mock_secret_repo,
        "session": mock_session,
        "http_client": mock_http_client,
        "retry_policy": mock_retry_policy,
    }


# ------------------------------------------------------------------------------------
# 1. Problem 1 Tests: Stuck Delivery Lease Reaper (reap_stuck_deliveries)
# ------------------------------------------------------------------------------------
@pytest.mark.unit
class TestReapStuckDeliveries:
    async def test_reap_returns_zero_when_no_stuck_deliveries(self, mock_deps):
        """When no deliveries are stuck in 'delivering', reaper returns 0 and does nothing."""
        mock_deps["delivery_repo"].get_stuck_deliveries_for_update.return_value = []

        reaped = await mock_deps["service"].reap_stuck_deliveries(timeout_seconds=300)

        assert reaped == 0
        mock_deps["attempt_repo"].create.assert_not_called()
        mock_deps["session"].commit.assert_not_called()

    @patch("src.services.delivery.deliver_webhook_task")
    async def test_reap_schedules_retry_for_eligible_delivery(self, mock_task, mock_deps):
        """Stuck delivery within retry limits is marked as 'retrying', attempt is logged, and task is dispatched."""
        stuck_delivery = _create_mock_delivery(retry_count=0, attempt=1, max_retries=3)
        mock_deps["delivery_repo"].get_stuck_deliveries_for_update.return_value = [stuck_delivery]
        mock_deps["retry_policy"].should_retry.return_value = True
        mock_deps["retry_policy"].compute_delay.return_value = 15

        reaped = await mock_deps["service"].reap_stuck_deliveries(timeout_seconds=300)

        assert reaped == 1
        # Attempt logged for the crash
        mock_deps["attempt_repo"].create.assert_awaited_once()
        create_kwargs = mock_deps["attempt_repo"].create.call_args.kwargs
        assert create_kwargs["delivery_id"] == stuck_delivery.id
        assert create_kwargs["attempt_number"] == 1
        assert "Worker terminated unexpectedly" in create_kwargs["error_message"]

        # Delivery marked as RETRYING with incremented counters
        mock_deps["delivery_repo"].mark_as_retrying.assert_awaited_once()
        retry_kwargs = mock_deps["delivery_repo"].mark_as_retrying.call_args.kwargs
        assert retry_kwargs["attempt"] == 2
        assert retry_kwargs["retry_count"] == 1

        # DB Committed
        assert mock_deps["session"].commit.await_count >= 1

        # Task enqueued with countdown
        mock_task.apply_async.assert_called_once_with(
            args=[str(stuck_delivery.id)],
            countdown=15,
        )

    @patch("src.services.delivery.deliver_webhook_task")
    async def test_reap_marks_dead_letter_when_max_retries_reached(self, mock_task, mock_deps):
        """Stuck delivery exceeding max retries transitions to dead_letter with NO task dispatch."""
        stuck_delivery = _create_mock_delivery(retry_count=2, attempt=3, max_retries=3)
        mock_deps["delivery_repo"].get_stuck_deliveries_for_update.return_value = [stuck_delivery]

        reaped = await mock_deps["service"].reap_stuck_deliveries(timeout_seconds=300)

        assert reaped == 1
        mock_deps["attempt_repo"].create.assert_awaited_once()
        mock_deps["delivery_repo"].mark_as_dead_letter.assert_awaited_once()
        dead_letter_kwargs = mock_deps["delivery_repo"].mark_as_dead_letter.call_args.kwargs
        assert dead_letter_kwargs["attempt"] == 4
        assert dead_letter_kwargs["retry_count"] == 3
        assert "Exceeded max retries" in dead_letter_kwargs["error_message"]

        assert mock_deps["session"].commit.await_count >= 1
        mock_task.apply_async.assert_not_called()

    @patch("src.services.delivery.deliver_webhook_task")
    async def test_reap_marks_dead_letter_when_policy_denies_retry(self, mock_task, mock_deps):
        """If policy dictates no retry, transitions directly to dead_letter."""
        stuck_delivery = _create_mock_delivery(retry_count=0, attempt=1, max_retries=3)
        mock_deps["delivery_repo"].get_stuck_deliveries_for_update.return_value = [stuck_delivery]
        mock_deps["retry_policy"].should_retry.return_value = False

        reaped = await mock_deps["service"].reap_stuck_deliveries(timeout_seconds=300)

        assert reaped == 1
        mock_deps["delivery_repo"].mark_as_dead_letter.assert_awaited_once()
        mock_task.apply_async.assert_not_called()

    @patch("src.services.delivery.deliver_webhook_task")
    async def test_reap_multiple_mixed_deliveries_batch(self, mock_task, mock_deps):
        """Handles a batch with both retryable and non-retryable deliveries cleanly."""
        d1 = _create_mock_delivery(retry_count=0, max_retries=3)  # retryable
        d2 = _create_mock_delivery(retry_count=2, max_retries=3)  # dead_letter
        mock_deps["delivery_repo"].get_stuck_deliveries_for_update.return_value = [d1, d2]
        mock_deps["retry_policy"].should_retry.side_effect = [True, False]
        mock_deps["retry_policy"].compute_delay.return_value = 5

        reaped = await mock_deps["service"].reap_stuck_deliveries(timeout_seconds=300)

        assert reaped == 2
        mock_deps["delivery_repo"].mark_as_retrying.assert_awaited_once()
        mock_deps["delivery_repo"].mark_as_dead_letter.assert_awaited_once()
        assert mock_task.apply_async.call_count == 1
        mock_task.apply_async.assert_called_with(args=[str(d1.id)], countdown=5)

    @patch("src.services.delivery.deliver_webhook_task")
    async def test_reap_rolls_back_and_skips_task_dispatch_on_commit_failure(
        self, mock_task, mock_deps
    ):
        """If database commit fails during reap, session is rolled back and no task is enqueued."""
        stuck_delivery = _create_mock_delivery(retry_count=0, max_retries=3)
        mock_deps["delivery_repo"].get_stuck_deliveries_for_update.return_value = [stuck_delivery]
        mock_deps["session"].commit.side_effect = RuntimeError("Database connection lost")

        with pytest.raises(RuntimeError, match="Database connection lost"):
            await mock_deps["service"].reap_stuck_deliveries(timeout_seconds=300)

        mock_deps["session"].rollback.assert_awaited_once()
        mock_task.apply_async.assert_not_called()

    @patch("src.tasks.webhook.get_async_db_context")
    @patch("src.services.delivery.DeliveryService")
    def test_reap_stuck_deliveries_celery_task(self, mock_service_cls, mock_db_ctx):
        """Celery task reap_stuck_deliveries_task successfully executes and returns count."""
        mock_session = AsyncMock()
        mock_db_ctx.return_value.__aenter__.return_value = mock_session

        mock_instance = AsyncMock()
        mock_instance.reap_stuck_deliveries.return_value = 5
        mock_service_cls.return_value = mock_instance

        count = reap_stuck_deliveries_task(timeout_seconds=300, batch_size=50)

        assert count == 5
        mock_instance.reap_stuck_deliveries.assert_awaited_once_with(
            timeout_seconds=300,
            batch_size=50,
        )


# ------------------------------------------------------------------------------------
# 2. Problem 2 Tests: Race Condition Prevention & Post-Commit Dispatch
# ------------------------------------------------------------------------------------
@pytest.mark.unit
class TestDeliverRaceConditionPrevention:
    @patch("src.services.delivery.deliver_webhook_task")
    async def test_deliver_dispatches_task_strictly_after_commit_on_retryable_http_status(
        self,
        mock_task,
        mock_deps,
    ):
        """Verifies Celery task is dispatched strictly AFTER DB commit on HTTP 500 retryable error."""
        delivery = _create_mock_delivery(retry_count=0, attempt=1, max_retries=3)
        mock_deps["delivery_repo"].get_delivery_for_processing.return_value = delivery
        mock_deps["secret_repo"].get_by_version.return_value = None
        mock_deps["secret_repo"].get_active_secret.return_value = None

        # Simulate HTTP 500 response
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 500
        mock_response.content = b'{"error": "internal error"}'
        mock_response.headers = {}
        mock_response.json.return_value = {"error": "internal error"}
        mock_deps["http_client"].post.return_value = mock_response

        mock_deps["retry_policy"].should_retry.return_value = True
        mock_deps["retry_policy"].compute_delay.return_value = 20

        # Track execution call order
        call_order = []
        mock_deps["session"].commit.side_effect = lambda: call_order.append("db_commit")
        mock_task.apply_async.side_effect = lambda *args, **kwargs: call_order.append(
            "redis_dispatch"
        )

        await mock_deps["service"].deliver(delivery_id=delivery.id)

        # Session commit is called twice: once when entering delivering, once after attempt
        assert "db_commit" in call_order
        assert "redis_dispatch" in call_order
        # The redis dispatch MUST happen strictly after the final db_commit!
        assert call_order[-1] == "redis_dispatch"
        assert call_order[-2] == "db_commit"

        mock_task.apply_async.assert_called_once_with(
            args=[str(delivery.id)],
            countdown=20,
        )

    @patch("src.services.delivery.deliver_webhook_task")
    async def test_deliver_dispatches_task_strictly_after_commit_on_timeout(
        self,
        mock_task,
        mock_deps,
    ):
        """Verifies Celery task is dispatched strictly AFTER DB commit on httpx.TimeoutException."""
        delivery = _create_mock_delivery(retry_count=0, attempt=1, max_retries=3)
        mock_deps["delivery_repo"].get_delivery_for_processing.return_value = delivery
        mock_deps["secret_repo"].get_by_version.return_value = None
        mock_deps["secret_repo"].get_active_secret.return_value = None

        # Simulate timeout exception
        mock_deps["http_client"].post.side_effect = httpx.ReadTimeout("Read timed out")
        mock_deps["retry_policy"].should_retry.return_value = True
        mock_deps["retry_policy"].compute_delay.return_value = 10

        call_order = []
        mock_deps["session"].commit.side_effect = lambda: call_order.append("db_commit")
        mock_task.apply_async.side_effect = lambda *args, **kwargs: call_order.append(
            "redis_dispatch"
        )

        await mock_deps["service"].deliver(delivery_id=delivery.id)

        assert call_order[-1] == "redis_dispatch"
        assert call_order[-2] == "db_commit"
        mock_task.apply_async.assert_called_once_with(
            args=[str(delivery.id)],
            countdown=10,
        )

    @patch("src.services.delivery.deliver_webhook_task")
    async def test_deliver_never_dispatches_task_if_db_commit_fails(
        self,
        mock_task,
        mock_deps,
    ):
        """If the final database commit fails, the transaction is rolled back and Redis is NEVER called."""
        delivery = _create_mock_delivery(retry_count=0, attempt=1, max_retries=3)
        mock_deps["delivery_repo"].get_delivery_for_processing.return_value = delivery
        mock_deps["secret_repo"].get_by_version.return_value = None
        mock_deps["secret_repo"].get_active_secret.return_value = None

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 502
        mock_response.content = b""
        mock_response.headers = {}
        mock_deps["http_client"].post.return_value = mock_response

        mock_deps["retry_policy"].should_retry.return_value = True
        mock_deps["retry_policy"].compute_delay.return_value = 10

        # Commit 1: mark_as_delivering, Commit 2: initial sync_event_status, Commit 3: post-attempt commit raises
        mock_deps["session"].commit.side_effect = [
            None,
            None,
            RuntimeError("DB deadlock / write failure"),
        ]

        with pytest.raises(RuntimeError, match="DB deadlock / write failure"):
            await mock_deps["service"].deliver(delivery_id=delivery.id)

        mock_deps["session"].rollback.assert_awaited_once()
        # Redis dispatch MUST NOT be called!
        mock_task.apply_async.assert_not_called()

    @patch("src.services.delivery.deliver_webhook_task")
    async def test_deliver_never_dispatches_task_if_event_sync_fails(
        self,
        mock_task,
        mock_deps,
    ):
        """If _sync_event_status fails, transaction is rolled back and Redis task is skipped."""
        delivery = _create_mock_delivery(retry_count=0, attempt=1, max_retries=3)
        mock_deps["delivery_repo"].get_delivery_for_processing.return_value = delivery
        mock_deps["secret_repo"].get_by_version.return_value = None
        mock_deps["secret_repo"].get_active_secret.return_value = None

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 500
        mock_response.content = b""
        mock_response.headers = {}
        mock_deps["http_client"].post.return_value = mock_response

        # _sync_event_status fails on second invocation
        mock_deps["event_repo"].resolve_and_update_status.side_effect = [
            True,
            RuntimeError("Event lock timeout"),
        ]

        with pytest.raises(RuntimeError, match="Event lock timeout"):
            await mock_deps["service"].deliver(delivery_id=delivery.id)

        mock_deps["session"].rollback.assert_awaited_once()
        mock_task.apply_async.assert_not_called()

    @patch("src.services.delivery.deliver_webhook_task")
    async def test_deliver_successful_http_never_dispatches_task(
        self,
        mock_task,
        mock_deps,
    ):
        """Successful delivery (HTTP 200) marks success and never dispatches retry task."""
        delivery = _create_mock_delivery(status=WebhookDeliveryStatus.DELIVERING)
        mock_deps["delivery_repo"].get_delivery_for_processing.return_value = delivery
        mock_deps["secret_repo"].get_by_version.return_value = None
        mock_deps["secret_repo"].get_active_secret.return_value = None

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.content = b'{"ok": true}'
        mock_response.headers = {}
        mock_response.json.return_value = {"ok": True}
        mock_deps["http_client"].post.return_value = mock_response

        await mock_deps["service"].deliver(delivery_id=delivery.id)

        mock_deps["delivery_repo"].mark_as_success.assert_awaited_once()
        mock_task.apply_async.assert_not_called()

    @patch("src.services.delivery.deliver_webhook_task")
    async def test_deliver_permanent_failure_never_dispatches_task(
        self,
        mock_task,
        mock_deps,
    ):
        """Permanent HTTP 400 (client error) marks failure without retry."""
        delivery = _create_mock_delivery(status=WebhookDeliveryStatus.DELIVERING)
        mock_deps["delivery_repo"].get_delivery_for_processing.return_value = delivery
        mock_deps["secret_repo"].get_by_version.return_value = None
        mock_deps["secret_repo"].get_active_secret.return_value = None

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.content = b'{"error": "bad request"}'
        mock_response.headers = {}
        mock_response.json.return_value = {"error": "bad request"}
        mock_deps["http_client"].post.return_value = mock_response

        mock_deps["retry_policy"].should_retry.return_value = False

        await mock_deps["service"].deliver(delivery_id=delivery.id)

        mock_deps["delivery_repo"].mark_as_failed.assert_awaited_once()
        mock_task.apply_async.assert_not_called()

    @patch("src.services.delivery.deliver_webhook_task")
    async def test_deliver_ssrf_blocked_marks_failed_without_retry(
        self,
        mock_task,
        mock_deps,
    ):
        """SSRF violation is a security exception: marked as permanent failure without retry."""
        delivery = _create_mock_delivery(status=WebhookDeliveryStatus.DELIVERING)
        mock_deps["delivery_repo"].get_delivery_for_processing.return_value = delivery
        mock_deps["secret_repo"].get_by_version.return_value = None
        mock_deps["secret_repo"].get_active_secret.return_value = None

        mock_deps["http_client"].post.side_effect = SSRFSecurityError("Resolved to 127.0.0.1")

        await mock_deps["service"].deliver(delivery_id=delivery.id)

        mock_deps["delivery_repo"].mark_as_failed.assert_awaited_once()
        mock_task.apply_async.assert_not_called()

    @patch("src.services.delivery.deliver_webhook_task")
    async def test_deliver_invalid_url_marks_failed_without_retry(
        self,
        mock_task,
        mock_deps,
    ):
        """Malformed URL is a permanent failure without retry."""
        delivery = _create_mock_delivery(status=WebhookDeliveryStatus.DELIVERING)
        mock_deps["delivery_repo"].get_delivery_for_processing.return_value = delivery
        mock_deps["secret_repo"].get_by_version.return_value = None
        mock_deps["secret_repo"].get_active_secret.return_value = None

        mock_deps["http_client"].post.side_effect = httpx.InvalidURL("Invalid URL format")

        await mock_deps["service"].deliver(delivery_id=delivery.id)

        mock_deps["delivery_repo"].mark_as_failed.assert_awaited_once()
        mock_task.apply_async.assert_not_called()


# ------------------------------------------------------------------------------------
# 3. Unit Tests: _process_retry_or_failure helper
# ------------------------------------------------------------------------------------
@pytest.mark.unit
class TestProcessRetryOrFailure:
    async def test_returns_delay_when_retrying(self, mock_deps):
        delivery = _create_mock_delivery(retry_count=0, max_retries=3)
        mock_deps["retry_policy"].should_retry.return_value = True
        mock_deps["retry_policy"].compute_delay.return_value = 25

        delay = await mock_deps["service"]._process_retry_or_failure(
            delivery=delivery,
            error_message="HTTP 503",
            should_retry=True,
            max_retries=3,
            duration_ms=100,
            status_code=503,
        )

        assert delay == 25
        mock_deps["delivery_repo"].mark_as_retrying.assert_awaited_once()

    async def test_returns_none_when_should_retry_false(self, mock_deps):
        delivery = _create_mock_delivery()
        delay = await mock_deps["service"]._process_retry_or_failure(
            delivery=delivery,
            error_message="Hard failure",
            should_retry=False,
            max_retries=3,
            duration_ms=100,
        )

        assert delay is None
        mock_deps["delivery_repo"].mark_as_failed.assert_awaited_once()

    async def test_returns_none_when_max_retries_exceeded(self, mock_deps):
        delivery = _create_mock_delivery(retry_count=2, max_retries=3)
        mock_deps["retry_policy"].should_retry.return_value = False

        delay = await mock_deps["service"]._process_retry_or_failure(
            delivery=delivery,
            error_message="Out of retries",
            should_retry=True,
            max_retries=3,
            duration_ms=100,
            status_code=500,
        )

        assert delay is None
        mock_deps["delivery_repo"].mark_as_dead_letter.assert_awaited_once()
