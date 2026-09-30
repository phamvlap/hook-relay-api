"""API integration tests for Webhook Events (/api/v1/events).

Covers:
- Authentication & Authorization
- Input Validation
- Event Ingestion (Fan-out to Active Endpoints, Celery Task Dispatch)
- Events with Zero Active Endpoints (auto-completed)
- Idempotency Key Deduplication
- Event Listing & Status Filtering
- Event Retrieval & Event Deliveries Association
"""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError

from src.models.event import WebhookEventStatus


# ---------------------------------------------------------------------------
# 1. Authentication
# ---------------------------------------------------------------------------
@pytest.mark.api
async def test_events_unauthorized_without_auth(async_client: AsyncClient):
    """Ensures event endpoints reject unauthenticated requests with 401."""
    assert (await async_client.get("/api/v1/events")).status_code == 401
    assert (await async_client.post("/api/v1/events", json={})).status_code == 401
    random_id = uuid4()
    assert (await async_client.get(f"/api/v1/events/{random_id}")).status_code == 401
    assert (await async_client.get(f"/api/v1/events/{random_id}/deliveries")).status_code == 401


# ---------------------------------------------------------------------------
# 2. Validation
# ---------------------------------------------------------------------------
@pytest.mark.api
@pytest.mark.parametrize(
    "payload",
    [
        {"payload": {"foo": "bar"}},  # missing event_type
        {"event_type": "", "payload": {"foo": "bar"}},  # empty event_type
        {"event_type": "   ", "payload": {"foo": "bar"}},  # whitespace-only event_type
        {"event_type": "user.signup", "payload": "not-a-dict"},  # invalid payload type
    ],
)
async def test_create_event_invalid_payload_returns_422(
    test_owner_auth,
    async_client: AsyncClient,
    payload: dict,
):
    """Ensures missing event_type or invalid payload triggers 422 Unprocessable Entity."""
    response = await async_client.post("/api/v1/events", json=payload)
    assert response.status_code == 422
    assert "error" in response.json()


@pytest.mark.api
async def test_create_event_payload_exceeding_max_size_returns_422(
    test_owner_auth,
    async_client: AsyncClient,
):
    """Ensures event payloads exceeding 1MB limit trigger 422 Unprocessable Entity."""
    oversized_payload = {
        "event_type": "large.upload",
        "payload": {"big_data": "x" * (1024 * 1024 + 100)},
    }
    response = await async_client.post("/api/v1/events", json=oversized_payload)
    assert response.status_code == 422
    assert "error" in response.json()


# ---------------------------------------------------------------------------
# 3. Ingestion & Fan-out
# ---------------------------------------------------------------------------
@pytest.mark.api
async def test_create_event_without_endpoints_auto_completes(
    test_owner_auth,
    async_client: AsyncClient,
):
    """When an owner has no active endpoints, the ingested event is marked as COMPLETED."""
    payload = {
        "event_type": "invoice.paid",
        "payload": {"invoice_id": "inv_123", "amount": 99.99},
    }
    response = await async_client.post("/api/v1/events", json=payload)
    assert response.status_code == 202
    data = response.json()

    assert data["event_type"] == payload["event_type"]
    assert data["payload"] == payload["payload"]
    assert data["status"] == WebhookEventStatus.COMPLETED.value
    assert "id" in data
    assert "created_at" in data


@pytest.mark.api
async def test_create_event_fans_out_to_active_endpoints(
    test_owner_auth,
    async_client: AsyncClient,
    mocker,
):
    """When active endpoints exist, deliveries are generated for each and Celery tasks dispatched."""
    # 1. Create two active endpoints and one paused endpoint
    ep1_res = await async_client.post(
        "/api/v1/endpoints",
        json={"name": "EP 1", "url": "https://example.com/ep1"},
    )
    ep2_res = await async_client.post(
        "/api/v1/endpoints",
        json={"name": "EP 2", "url": "https://example.com/ep2"},
    )
    ep3_res = await async_client.post(
        "/api/v1/endpoints",
        json={"name": "EP 3", "url": "https://example.com/ep3"},
    )
    # Pause ep3
    await async_client.patch(f"/api/v1/endpoints/{ep3_res.json()['id']}/pause")

    # 2. Spy on Celery task dispatch
    mock_task = mocker.patch("src.services.event.deliver_webhook_task.delay")

    # 3. Ingest event
    payload = {
        "event_type": "order.completed",
        "payload": {"order_id": "ord_999"},
    }
    response = await async_client.post("/api/v1/events", json=payload)
    assert response.status_code == 202
    event_data = response.json()
    event_id = event_data["id"]

    # Only active endpoints (ep1 and ep2) receive deliveries
    assert mock_task.call_count == 2

    # 4. Check /api/v1/events/{event_id}/deliveries
    delivery_res = await async_client.get(f"/api/v1/events/{event_id}/deliveries")
    assert delivery_res.status_code == 200
    deliveries_data = delivery_res.json()
    assert deliveries_data["total"] == 2
    endpoint_ids = {d["endpoint"]["id"] for d in deliveries_data["items"]}
    assert ep1_res.json()["id"] in endpoint_ids
    assert ep2_res.json()["id"] in endpoint_ids
    assert ep3_res.json()["id"] not in endpoint_ids


# ---------------------------------------------------------------------------
# 4. Idempotency Key Deduplication
# ---------------------------------------------------------------------------
@pytest.mark.api
async def test_create_event_idempotency_key_deduplication(
    test_owner_auth,
    async_client: AsyncClient,
):
    """Subsequent requests with identical Idempotency-Key return the original event."""
    idempotency_key = "idempotency_test_trans_12345"
    payload = {
        "event_type": "payment.authorized",
        "payload": {"tx": "tx_abc"},
    }
    headers = {"Idempotency-Key": idempotency_key}

    # First attempt -> creates event
    res_1 = await async_client.post("/api/v1/events", json=payload, headers=headers)
    assert res_1.status_code == 202
    event_1 = res_1.json()

    # Second attempt with same key -> returns existing event with same ID
    res_2 = await async_client.post(
        "/api/v1/events",
        json={"event_type": "different.type", "payload": {}},
        headers=headers,
    )
    assert res_2.status_code == 202
    event_2 = res_2.json()

    assert event_1["id"] == event_2["id"]
    assert event_2["event_type"] == "payment.authorized"


# ---------------------------------------------------------------------------
# 5. Listing & Retrieval
# ---------------------------------------------------------------------------
@pytest.mark.api
async def test_list_events_pagination_and_status_filter(
    test_owner_auth,
    async_client: AsyncClient,
):
    """Verifies listing events with pagination and filtering by WebhookEventStatus."""
    # Create 3 events
    for i in range(3):
        await async_client.post(
            "/api/v1/events",
            json={"event_type": f"event.{i}", "payload": {"seq": i}},
        )

    # Paginate with page_size=2
    list_res = await async_client.get(
        "/api/v1/events",
        params={"page": 1, "page_size": 2},
    )
    assert list_res.status_code == 200
    paged = list_res.json()
    assert paged["total"] == 3
    assert len(paged["items"]) == 2

    # Filter by status=completed (since no active endpoints existed, all are completed)
    filter_res = await async_client.get(
        "/api/v1/events",
        params={"status": "completed"},
    )
    assert filter_res.status_code == 200
    assert filter_res.json()["total"] == 3

    # Filter by status=failed
    failed_res = await async_client.get(
        "/api/v1/events",
        params={"status": "failed"},
    )
    assert failed_res.status_code == 200
    assert failed_res.json()["total"] == 0


@pytest.mark.api
async def test_get_event_by_id_and_not_found(
    test_owner_auth,
    async_client: AsyncClient,
):
    """Verifies retrieving event by ID and 404 for unknown IDs."""
    created = (
        await async_client.post(
            "/api/v1/events",
            json={"event_type": "account.created", "payload": {"id": 1}},
        )
    ).json()

    # Success 200
    res = await async_client.get(f"/api/v1/events/{created['id']}")
    assert res.status_code == 200
    assert res.json()["id"] == created["id"]
    assert res.json()["event_type"] == "account.created"

    # Nonexistent -> 404
    assert (await async_client.get(f"/api/v1/events/{uuid4()}")).status_code == 404


@pytest.mark.api
async def test_list_event_deliveries_pagination_and_not_found(
    test_owner_auth,
    async_client: AsyncClient,
):
    """Verifies pagination on /api/v1/events/{event_id}/deliveries and empty results for unknown IDs."""
    # Create 3 endpoints
    for i in range(3):
        await async_client.post(
            "/api/v1/endpoints",
            json={"name": f"EP {i}", "url": f"https://example.com/deliv-ep-{i}"},
        )

    # Ingest event -> fans out to 3 deliveries
    event_res = await async_client.post(
        "/api/v1/events",
        json={"event_type": "item.purchased", "payload": {"item_id": 42}},
    )
    assert event_res.status_code == 202
    event_id = event_res.json()["id"]

    # Paginate deliveries (page_size = 2)
    delivery_res = await async_client.get(
        f"/api/v1/events/{event_id}/deliveries",
        params={"page": 1, "page_size": 2},
    )
    assert delivery_res.status_code == 200
    delivery_data = delivery_res.json()
    assert delivery_data["total"] == 3
    assert len(delivery_data["items"]) == 2
    assert delivery_data["next"] is not None

    # Deliveries for nonexistent event
    empty_res = await async_client.get(f"/api/v1/events/{uuid4()}/deliveries")
    assert empty_res.status_code == 200
    assert empty_res.json()["total"] == 0
    assert empty_res.json()["items"] == []


@pytest.mark.api
async def test_create_event_concurrent_integrity_error_deduplication(
    test_owner_auth,
    async_client: AsyncClient,
    mocker,
):
    """Verifies that race-condition IntegrityError falls back to idempotency lookup or raises 409."""
    # 1. First event created successfully
    idem_key = "race_condition_test_key"
    first_res = await async_client.post(
        "/api/v1/events",
        json={"event_type": "race.test", "payload": {"foo": "bar"}},
        headers={"Idempotency-Key": idem_key},
    )
    assert first_res.status_code == 202
    first_id = first_res.json()["id"]

    # 2. Simulate concurrent insert hitting unique constraint:
    # Repository create raises IntegrityError
    mocker.patch(
        "src.repositories.event.EventRepository.create",
        side_effect=IntegrityError("duplicate key", {}, Exception()),
    )

    # With Idempotency-Key -> catches IntegrityError and retrieves existing event
    race_res = await async_client.post(
        "/api/v1/events",
        json={"event_type": "race.test", "payload": {"foo": "bar"}},
        headers={"Idempotency-Key": idem_key},
    )
    assert race_res.status_code == 202
    assert race_res.json()["id"] == first_id

    # Without Idempotency-Key -> catches IntegrityError and raises 409 Conflict
    conflict_res = await async_client.post(
        "/api/v1/events",
        json={"event_type": "race.test", "payload": {"foo": "bar"}},
    )
    assert conflict_res.status_code == 409
