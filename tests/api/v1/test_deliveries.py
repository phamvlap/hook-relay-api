"""API integration tests for Webhook Deliveries (/api/v1/deliveries).

Covers:
- Authentication & Authorization
- Delivery Listing, Filtering (status, event_id, endpoint_id) & Pagination
- Delivery Retrieval
- Execution Attempt Listing
- Manual Dead-Letter Retries (Eligibility checks, Endpoint Status checks, Celery Task Dispatch)
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from src.models.delivery import WebhookDelivery, WebhookDeliveryAttempt, WebhookDeliveryStatus


# ---------------------------------------------------------------------------
# 1. Authentication
# ---------------------------------------------------------------------------
@pytest.mark.api
async def test_deliveries_unauthorized_without_auth(async_client: AsyncClient):
    """Ensures delivery endpoints reject unauthenticated requests with 401."""
    assert (await async_client.get("/api/v1/deliveries")).status_code == 401
    random_id = uuid4()
    assert (await async_client.get(f"/api/v1/deliveries/{random_id}")).status_code == 401
    assert (await async_client.get(f"/api/v1/deliveries/{random_id}/attempts")).status_code == 401
    assert (await async_client.post(f"/api/v1/deliveries/{random_id}/retry")).status_code == 401


# ---------------------------------------------------------------------------
# 2. Listing & Filtering
# ---------------------------------------------------------------------------
@pytest.mark.api
async def test_list_deliveries_empty(
    test_owner_auth,
    async_client: AsyncClient,
):
    """Verifies that an owner with no deliveries receives an empty paginated list."""
    response = await async_client.get("/api/v1/deliveries")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["items"] == []


@pytest.mark.api
async def test_list_deliveries_pagination_and_filters(
    test_owner_auth,
    async_client: AsyncClient,
):
    """Verifies listing deliveries with event_id, endpoint_id, status filters and pagination."""
    # 1. Create two endpoints
    (
        await async_client.post(
            "/api/v1/endpoints", json={"name": "EP 1", "url": "https://example.com/ep1"}
        )
    ).json()
    ep2 = (
        await async_client.post(
            "/api/v1/endpoints", json={"name": "EP 2", "url": "https://example.com/ep2"}
        )
    ).json()

    # 2. Ingest two events -> generates 4 deliveries (2 events x 2 active endpoints)
    ev1 = (
        await async_client.post("/api/v1/events", json={"event_type": "item.one", "payload": {}})
    ).json()
    (
        await async_client.post("/api/v1/events", json={"event_type": "item.two", "payload": {}})
    ).json()

    # 3. List all deliveries
    all_res = await async_client.get("/api/v1/deliveries")
    assert all_res.status_code == 200
    assert all_res.json()["total"] == 4

    # 4. Filter by event_id
    by_ev1 = await async_client.get(
        "/api/v1/deliveries",
        params={"event_id": str(ev1["id"])},
    )
    assert by_ev1.status_code == 200
    assert by_ev1.json()["total"] == 2
    assert all(d["event"]["id"] == ev1["id"] for d in by_ev1.json()["items"])

    # 5. Filter by endpoint_id
    by_ep2 = await async_client.get(
        "/api/v1/deliveries",
        params={"endpoint_id": str(ep2["id"])},
    )
    assert by_ep2.status_code == 200
    assert by_ep2.json()["total"] == 2
    assert all(d["endpoint"]["id"] == ep2["id"] for d in by_ep2.json()["items"])

    # 6. Filter by status=queued
    by_status = await async_client.get(
        "/api/v1/deliveries",
        params={"status": "queued"},
    )
    assert by_status.status_code == 200
    assert by_status.json()["total"] == 4

    # 7. Pagination (page_size=2)
    paged = await async_client.get(
        "/api/v1/deliveries",
        params={"page": 1, "page_size": 2},
    )
    assert paged.status_code == 200
    assert paged.json()["total"] == 4
    assert len(paged.json()["items"]) == 2
    assert paged.json()["next"] is not None


# ---------------------------------------------------------------------------
# 3. Retrieval
# ---------------------------------------------------------------------------
@pytest.mark.api
async def test_get_delivery_by_id_and_not_found(
    test_owner_auth,
    async_client: AsyncClient,
):
    """Verifies retrieving single delivery by ID and 404 for nonexistent delivery."""
    # Create endpoint + event
    ep = (
        await async_client.post(
            "/api/v1/endpoints", json={"name": "EP", "url": "https://example.com/ep"}
        )
    ).json()
    ev = (
        await async_client.post("/api/v1/events", json={"event_type": "test.event", "payload": {}})
    ).json()

    deliveries = (await async_client.get(f"/api/v1/events/{ev['id']}/deliveries")).json()["items"]
    assert len(deliveries) == 1
    delivery_id = deliveries[0]["id"]

    # Success 200
    res = await async_client.get(f"/api/v1/deliveries/{delivery_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == delivery_id
    assert data["event"]["id"] == ev["id"]
    assert data["endpoint"]["id"] == ep["id"]
    assert data["status"] == WebhookDeliveryStatus.QUEUED.value

    # Nonexistent -> 404
    assert (await async_client.get(f"/api/v1/deliveries/{uuid4()}")).status_code == 404


# ---------------------------------------------------------------------------
# 4. Delivery Attempts
# ---------------------------------------------------------------------------
@pytest.mark.api
async def test_get_delivery_attempts(
    test_owner_auth,
    async_client: AsyncClient,
    db_session: Session,
):
    """Verifies listing immutable execution attempts for a delivery."""
    # 1. Setup endpoint and event to create delivery
    await async_client.post(
        "/api/v1/endpoints", json={"name": "EP", "url": "https://example.com/ep"}
    )
    ev = (
        await async_client.post("/api/v1/events", json={"event_type": "ev", "payload": {}})
    ).json()
    delivery_id = (await async_client.get(f"/api/v1/events/{ev['id']}/deliveries")).json()["items"][
        0
    ]["id"]

    # 2. Initially 0 attempts
    empty_attempts = await async_client.get(f"/api/v1/deliveries/{delivery_id}/attempts")
    assert empty_attempts.status_code == 200
    assert empty_attempts.json()["total"] == 0

    # 3. Seed 2 attempts in database
    now = datetime.now(UTC)
    attempt1 = WebhookDeliveryAttempt(
        delivery_id=delivery_id,
        attempt_number=1,
        status_code=500,
        error_message="Internal Server Error",
        started_at=now,
        completed_at=now,
    )
    attempt2 = WebhookDeliveryAttempt(
        delivery_id=delivery_id,
        attempt_number=2,
        status_code=200,
        response_body={"received": True},
        started_at=now,
        completed_at=now,
    )
    db_session.add_all([attempt1, attempt2])
    db_session.flush()

    # 4. Query attempts
    res = await async_client.get(f"/api/v1/deliveries/{delivery_id}/attempts")
    assert res.status_code == 200
    attempts_data = res.json()
    assert attempts_data["total"] == 2
    assert attempts_data["items"][0]["attempt_number"] == 1
    assert attempts_data["items"][0]["status_code"] == 500
    assert attempts_data["items"][1]["attempt_number"] == 2
    assert attempts_data["items"][1]["status_code"] == 200

    # 5. Nonexistent delivery -> 404
    assert (await async_client.get(f"/api/v1/deliveries/{uuid4()}/attempts")).status_code == 404


@pytest.mark.api
async def test_get_delivery_attempts_pagination(
    test_owner_auth,
    async_client: AsyncClient,
    db_session: Session,
):
    """Verifies pagination on /api/v1/deliveries/{delivery_id}/attempts."""
    await async_client.post(
        "/api/v1/endpoints", json={"name": "EP Attempts", "url": "https://example.com/ep-attempts"}
    )
    ev = (
        await async_client.post("/api/v1/events", json={"event_type": "ev", "payload": {}})
    ).json()
    delivery_id = (await async_client.get(f"/api/v1/events/{ev['id']}/deliveries")).json()["items"][
        0
    ]["id"]

    now = datetime.now(UTC)
    for i in range(1, 4):
        attempt = WebhookDeliveryAttempt(
            delivery_id=delivery_id,
            attempt_number=i,
            status_code=500,
            started_at=now,
            completed_at=now,
        )
        db_session.add(attempt)
    db_session.flush()

    paged_res = await async_client.get(
        f"/api/v1/deliveries/{delivery_id}/attempts",
        params={"page": 1, "page_size": 2},
    )
    assert paged_res.status_code == 200
    data = paged_res.json()
    assert data["total"] == 3
    assert len(data["items"]) == 2
    assert data["next"] is not None


# ---------------------------------------------------------------------------
# 5. Manual Retries
# ---------------------------------------------------------------------------
@pytest.mark.api
async def test_retry_delivery_conflict_when_not_in_dead_letter(
    test_owner_auth,
    async_client: AsyncClient,
):
    """Verifies that non-dead_letter deliveries (e.g. queued, success) reject manual retry with 409."""
    await async_client.post(
        "/api/v1/endpoints", json={"name": "EP", "url": "https://example.com/ep"}
    )
    ev = (
        await async_client.post("/api/v1/events", json={"event_type": "ev", "payload": {}})
    ).json()
    delivery_id = (await async_client.get(f"/api/v1/events/{ev['id']}/deliveries")).json()["items"][
        0
    ]["id"]

    # Delivery is in QUEUED status -> 409 Conflict
    response = await async_client.post(f"/api/v1/deliveries/{delivery_id}/retry")
    assert response.status_code == 409
    assert "dead_letter" in response.json()["error"]["message"]


@pytest.mark.api
async def test_retry_delivery_conflict_when_endpoint_inactive(
    test_owner_auth,
    async_client: AsyncClient,
    db_session: Session,
):
    """Verifies that attempting to retry a delivery whose endpoint is paused returns 409 Conflict."""
    ep = (
        await async_client.post(
            "/api/v1/endpoints", json={"name": "EP", "url": "https://example.com/ep"}
        )
    ).json()
    ev = (
        await async_client.post("/api/v1/events", json={"event_type": "ev", "payload": {}})
    ).json()
    delivery_id = (await async_client.get(f"/api/v1/events/{ev['id']}/deliveries")).json()["items"][
        0
    ]["id"]

    # Set delivery to DEAD_LETTER in DB
    delivery = db_session.query(WebhookDelivery).filter_by(id=delivery_id).first()
    assert delivery is not None
    delivery.status = WebhookDeliveryStatus.DEAD_LETTER
    db_session.flush()

    # Pause the endpoint
    await async_client.patch(f"/api/v1/endpoints/{ep['id']}/pause")

    # Retry -> 409 Conflict because endpoint is paused
    response = await async_client.post(f"/api/v1/deliveries/{delivery_id}/retry")
    assert response.status_code == 409
    assert "inactive" in response.json()["error"]["message"]


@pytest.mark.api
async def test_retry_delivery_success_when_dead_letter_and_active(
    test_owner_auth,
    async_client: AsyncClient,
    db_session: Session,
    mocker,
):
    """Verifies that dead_letter delivery with an active endpoint successfully queues for retry."""
    await async_client.post(
        "/api/v1/endpoints", json={"name": "EP", "url": "https://example.com/ep"}
    )
    ev = (
        await async_client.post("/api/v1/events", json={"event_type": "ev", "payload": {}})
    ).json()
    delivery_id = (await async_client.get(f"/api/v1/events/{ev['id']}/deliveries")).json()["items"][
        0
    ]["id"]

    # Transition delivery to DEAD_LETTER
    delivery = db_session.query(WebhookDelivery).filter_by(id=delivery_id).first()
    assert delivery is not None
    delivery.status = WebhookDeliveryStatus.DEAD_LETTER
    db_session.flush()

    # Spy on Celery deliver_webhook_task
    mock_task = mocker.patch("src.services.delivery.deliver_webhook_task.delay")

    # Act: retry delivery
    response = await async_client.post(f"/api/v1/deliveries/{delivery_id}/retry")
    assert response.status_code == 200
    assert response.json()["success"] is True

    # Assert Celery task was scheduled
    mock_task.assert_called_once_with(str(delivery_id))

    # Assert delivery status updated in DB
    db_session.refresh(delivery)
    assert delivery.status == WebhookDeliveryStatus.QUEUED


@pytest.mark.api
async def test_retry_delivery_not_found(
    test_owner_auth,
    async_client: AsyncClient,
):
    # Nonexistent delivery retry -> 404
    response = await async_client.post(f"/api/v1/deliveries/{uuid4()}/retry")
    assert response.status_code == 404


@pytest.mark.api
async def test_retry_delivery_conflict_when_endpoint_deleted(
    test_owner_auth,
    async_client: AsyncClient,
    db_session: Session,
):
    """Verifies that attempting to retry a delivery whose endpoint is soft-deleted returns 409 Conflict."""
    ep = (
        await async_client.post(
            "/api/v1/endpoints", json={"name": "EP Del", "url": "https://example.com/ep-del"}
        )
    ).json()
    ev = (
        await async_client.post("/api/v1/events", json={"event_type": "ev.del", "payload": {}})
    ).json()
    delivery_id = (await async_client.get(f"/api/v1/events/{ev['id']}/deliveries")).json()["items"][
        0
    ]["id"]

    # Set delivery to DEAD_LETTER
    delivery = db_session.query(WebhookDelivery).filter_by(id=delivery_id).first()
    assert delivery is not None
    delivery.status = WebhookDeliveryStatus.DEAD_LETTER
    db_session.flush()

    # Soft-delete the endpoint
    del_res = await async_client.delete(f"/api/v1/endpoints/{ep['id']}")
    assert del_res.status_code == 204

    # Retry -> 409 Conflict because endpoint is deleted/inactive
    response = await async_client.post(f"/api/v1/deliveries/{delivery_id}/retry")
    assert response.status_code == 409
    assert "inactive" in response.json()["error"]["message"]
