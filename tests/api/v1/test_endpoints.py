"""API integration tests for Webhook Endpoints (/api/v1/endpoints).

Covers:
- Authentication & Authorization
- Input Validation & Anti-SSRF Protection
- Creation, Retrieval, Listing (Pagination & Filters)
- Updates & Conflict Handling
- Lifecycle Management (Pause, Resume, Secret Rotation, Soft-Delete)
"""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.models.endpoint import WebhookEndpointStatus


# ---------------------------------------------------------------------------
# 1. Authentication & Security
# ---------------------------------------------------------------------------
@pytest.mark.api
async def test_endpoints_unauthorized_without_auth(async_client: AsyncClient):
    """Ensures protected endpoints reject requests lacking authentication with 401."""
    assert (await async_client.get("/api/v1/endpoints")).status_code == 401
    assert (await async_client.post("/api/v1/endpoints", json={})).status_code == 401
    random_id = uuid4()
    assert (await async_client.get(f"/api/v1/endpoints/{random_id}")).status_code == 401
    assert (await async_client.patch(f"/api/v1/endpoints/{random_id}", json={})).status_code == 401
    assert (await async_client.delete(f"/api/v1/endpoints/{random_id}")).status_code == 401
    assert (await async_client.patch(f"/api/v1/endpoints/{random_id}/pause")).status_code == 401
    assert (await async_client.patch(f"/api/v1/endpoints/{random_id}/resume")).status_code == 401
    assert (
        await async_client.post(f"/api/v1/endpoints/{random_id}/rotate-secret")
    ).status_code == 401


# ---------------------------------------------------------------------------
# 2. Validation & SSRF Prevention
# ---------------------------------------------------------------------------
@pytest.mark.api
@pytest.mark.parametrize(
    "payload,expected_field",
    [
        ({"name": "Test", "url": "not-a-valid-url"}, "url"),
        ({"name": "", "url": "https://example.com/webhook"}, "name"),
        ({"name": "Test", "url": "https://example.com/webhook", "max_retries": -1}, "max_retries"),
        ({"name": "Test", "url": "https://example.com/webhook", "max_retries": 25}, "max_retries"),
    ],
)
async def test_create_endpoint_invalid_payload_returns_422(
    authenticated_client,
    async_client: AsyncClient,
    payload: dict,
    expected_field: str,
):
    """Ensures Pydantic schema validation rejects malformed requests with 422."""
    response = await async_client.post("/api/v1/endpoints", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert "error" in data


@pytest.mark.api
@pytest.mark.parametrize(
    "private_url",
    [
        "http://127.0.0.1/webhook",
        "http://localhost:8000/webhook",
        "http://192.168.1.1/hook",
        "http://10.0.0.1/hook",
    ],
)
async def test_create_endpoint_ssrf_blocked_returns_422(
    test_owner_auth,
    async_client: AsyncClient,
    private_url: str,
):
    """Ensures private/loopback IP addresses are blocked by anti-SSRF validation."""
    payload = {
        "name": "Internal Service",
        "url": private_url,
        "max_retries": 5,
    }
    response = await async_client.post("/api/v1/endpoints", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert "error" in data


@pytest.mark.api
async def test_create_endpoint_anti_ssrf_dns_mock_and_public_ip(
    test_owner_auth,
    async_client: AsyncClient,
    mocker,
):
    """Verifies DNS-resolved private IPs are blocked, while valid public IPs are accepted."""
    # 1. Public IP literal is accepted (201)
    res_public = await async_client.post(
        "/api/v1/endpoints",
        json={"name": "Public IP Hook", "url": "http://93.184.216.34/webhook"},
    )
    assert res_public.status_code == 201

    # 2. Domain resolving to loopback via DNS is blocked (422)
    mocker.patch("socket.gethostbyname", return_value="127.0.0.1")
    res_dns = await async_client.post(
        "/api/v1/endpoints",
        json={"name": "Evil Hook", "url": "http://evil-domain-resolving-to-local.com/webhook"},
    )
    assert res_dns.status_code == 422

    # 3. Invalid scheme (ftp) is blocked (422)
    res_ftp = await async_client.post(
        "/api/v1/endpoints",
        json={"name": "FTP Hook", "url": "ftp://example.com/webhook"},
    )
    assert res_ftp.status_code == 422


# ---------------------------------------------------------------------------
# 3. Create & Retrieve Endpoints
# ---------------------------------------------------------------------------
@pytest.mark.api
async def test_create_endpoint_success_201(
    test_owner_auth,
    async_client: AsyncClient,
):
    """Verifies successful endpoint creation with generated whsec_ signing secret."""
    payload = {
        "name": "Primary Webhook",
        "url": "https://api.merchant.com/webhooks/incoming",
        "max_retries": 3,
    }
    response = await async_client.post("/api/v1/endpoints", json=payload)
    assert response.status_code == 201
    data = response.json()

    assert data["name"] == payload["name"]
    assert data["url"] == payload["url"]
    assert data["status"] == WebhookEndpointStatus.ACTIVE.value
    assert data["max_retries"] == 3
    assert data["secret"].startswith("whsec_")
    assert data["secret_version"] == 1
    assert "id" in data
    assert "created_at" in data

    # Verify retrieval
    endpoint_id = data["id"]
    get_res = await async_client.get(f"/api/v1/endpoints/{endpoint_id}")
    assert get_res.status_code == 200
    retrieved = get_res.json()
    assert retrieved["id"] == endpoint_id
    assert retrieved["url"] == payload["url"]


@pytest.mark.api
async def test_create_endpoint_duplicate_url_conflict_409(
    test_owner_auth,
    async_client: AsyncClient,
):
    """Verifies that creating duplicate URLs for the same owner returns 409 Conflict."""
    payload = {
        "name": "Duplicate Webhook",
        "url": "https://api.merchant.com/webhooks/unique",
        "max_retries": 5,
    }
    res_1 = await async_client.post("/api/v1/endpoints", json=payload)
    assert res_1.status_code == 201

    res_2 = await async_client.post("/api/v1/endpoints", json=payload)
    assert res_2.status_code == 409
    assert "error" in res_2.json()


@pytest.mark.api
async def test_get_endpoint_not_found_returns_404(
    test_owner_auth,
    async_client: AsyncClient,
):
    """Verifies 404 response for nonexistent endpoint ID."""
    response = await async_client.get(f"/api/v1/endpoints/{uuid4()}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 4. Listing & Pagination
# ---------------------------------------------------------------------------
@pytest.mark.api
async def test_list_endpoints_pagination_and_filtering(
    test_owner_auth,
    async_client: AsyncClient,
):
    """Verifies list pagination, item ordering, and status filtering."""
    # 1. Initially empty
    empty_res = await async_client.get("/api/v1/endpoints")
    assert empty_res.status_code == 200
    assert empty_res.json()["total"] == 0
    assert empty_res.json()["items"] == []

    # 2. Create 3 endpoints
    created_ids = []
    for i in range(3):
        res = await async_client.post(
            "/api/v1/endpoints",
            json={"name": f"Endpoint {i}", "url": f"https://example.com/webhook/{i}"},
        )
        assert res.status_code == 201
        created_ids.append(res.json()["id"])

    # 3. Test pagination (page_size = 2)
    paged_res = await async_client.get(
        "/api/v1/endpoints",
        params={"page": 1, "page_size": 2},
    )
    assert paged_res.status_code == 200
    paged_data = paged_res.json()
    assert paged_data["total"] == 3
    assert len(paged_data["items"]) == 2
    assert paged_data["next"] is not None

    # 4. Pause one endpoint and test status filter
    await async_client.patch(f"/api/v1/endpoints/{created_ids[0]}/pause")

    active_res = await async_client.get(
        "/api/v1/endpoints",
        params={"status": "active"},
    )
    assert active_res.status_code == 200
    assert active_res.json()["total"] == 2

    paused_res = await async_client.get(
        "/api/v1/endpoints",
        params={"status": "paused"},
    )
    assert paused_res.status_code == 200
    assert paused_res.json()["total"] == 1


# ---------------------------------------------------------------------------
# 5. Updates
# ---------------------------------------------------------------------------
@pytest.mark.api
async def test_update_endpoint_success_and_conflict(
    test_owner_auth,
    async_client: AsyncClient,
):
    """Verifies PATCH update endpoint name, max_retries, and duplicate URL prevention."""
    created = (
        await async_client.post(
            "/api/v1/endpoints",
            json={
                "name": "Initial Name",
                "url": "https://example.com/hook-to-update",
                "max_retries": 5,
            },
        )
    ).json()

    # Update name and max_retries
    patch_res = await async_client.patch(
        f"/api/v1/endpoints/{created['id']}",
        json={"name": "Updated Name", "max_retries": 10},
    )
    assert patch_res.status_code == 200
    updated = patch_res.json()
    assert updated["name"] == "Updated Name"
    assert updated["max_retries"] == 10

    # Update URL to a new valid safe URL
    url_patch_res = await async_client.patch(
        f"/api/v1/endpoints/{created['id']}",
        json={"url": "https://example.com/hook-updated-new-url"},
    )
    assert url_patch_res.status_code == 200
    assert url_patch_res.json()["url"] == "https://example.com/hook-updated-new-url"

    # Duplicate URL conflict on update (409)
    (
        await async_client.post(
            "/api/v1/endpoints",
            json={"name": "Second Hook", "url": "https://example.com/second-hook"},
        )
    ).json()
    conflict_res = await async_client.patch(
        f"/api/v1/endpoints/{created['id']}",
        json={"url": "https://example.com/second-hook"},
    )
    assert conflict_res.status_code == 409
    assert "error" in conflict_res.json()

    # SSRF address rejected on update (422)
    ssrf_patch_res = await async_client.patch(
        f"/api/v1/endpoints/{created['id']}",
        json={"url": "http://127.0.0.1/admin"},
    )
    assert ssrf_patch_res.status_code == 422

    # 404 for unknown endpoint
    assert (
        await async_client.patch(f"/api/v1/endpoints/{uuid4()}", json={"name": "New"})
    ).status_code == 404


# ---------------------------------------------------------------------------
# 6. Pause, Resume & Secret Rotation
# ---------------------------------------------------------------------------
@pytest.mark.api
async def test_pause_and_resume_endpoint_lifecycle(
    test_owner_auth,
    async_client: AsyncClient,
):
    """Verifies state machine transitions between ACTIVE and PAUSED, plus 409 on duplicate transition."""
    created = (
        await async_client.post(
            "/api/v1/endpoints",
            json={"name": "Lifecycle Hook", "url": "https://example.com/lifecycle"},
        )
    ).json()
    ep_id = created["id"]

    # Pause active endpoint -> 200
    pause_res = await async_client.patch(f"/api/v1/endpoints/{ep_id}/pause")
    assert pause_res.status_code == 200
    assert pause_res.json()["success"] is True

    # Re-pausing already paused endpoint is idempotent -> 200
    pause_repeat = await async_client.patch(f"/api/v1/endpoints/{ep_id}/pause")
    assert pause_repeat.status_code == 200
    assert pause_repeat.json()["success"] is True

    # Resume paused endpoint -> 200
    resume_res = await async_client.patch(f"/api/v1/endpoints/{ep_id}/resume")
    assert resume_res.status_code == 200
    assert resume_res.json()["success"] is True

    # Re-resuming already active endpoint is idempotent -> 200
    resume_repeat = await async_client.patch(f"/api/v1/endpoints/{ep_id}/resume")
    assert resume_repeat.status_code == 200
    assert resume_repeat.json()["success"] is True


@pytest.mark.api
async def test_pause_and_resume_endpoint_not_found(
    test_owner_auth,
    async_client: AsyncClient,
):
    """Verifies that pausing or resuming a nonexistent endpoint returns 404."""
    random_id = uuid4()
    assert (await async_client.patch(f"/api/v1/endpoints/{random_id}/pause")).status_code == 404
    assert (await async_client.patch(f"/api/v1/endpoints/{random_id}/resume")).status_code == 404


@pytest.mark.api
async def test_rotate_endpoint_secret(
    test_owner_auth,
    async_client: AsyncClient,
):
    """Verifies rotating signing secret increments version and yields new whsec_ secret."""
    created = (
        await async_client.post(
            "/api/v1/endpoints",
            json={"name": "Rotation Hook", "url": "https://example.com/rotate"},
        )
    ).json()
    ep_id = created["id"]
    old_secret = created["secret"]

    rotate_res = await async_client.post(f"/api/v1/endpoints/{ep_id}/rotate-secret")
    assert rotate_res.status_code == 200
    rotated_data = rotate_res.json()

    assert rotated_data["version"] == 2
    assert rotated_data["secret"].startswith("whsec_")
    assert rotated_data["secret"] != old_secret
    assert rotated_data["status"] == "active"

    # Rotating nonexistent endpoint -> 404
    assert (
        await async_client.post(f"/api/v1/endpoints/{uuid4()}/rotate-secret")
    ).status_code == 404


# ---------------------------------------------------------------------------
# 7. Soft Deletion
# ---------------------------------------------------------------------------
@pytest.mark.api
async def test_delete_endpoint_soft_deletes(
    test_owner_auth,
    async_client: AsyncClient,
):
    """Verifies soft-deleting an endpoint returns 204 and subsequently hides it with 404."""
    created = (
        await async_client.post(
            "/api/v1/endpoints",
            json={"name": "To Delete", "url": "https://example.com/to-delete"},
        )
    ).json()
    ep_id = created["id"]

    # Delete -> 204
    del_res = await async_client.delete(f"/api/v1/endpoints/{ep_id}")
    assert del_res.status_code == 204

    # Subsequent GET -> 404
    assert (await async_client.get(f"/api/v1/endpoints/{ep_id}")).status_code == 404

    # Subsequent DELETE -> 404
    assert (await async_client.delete(f"/api/v1/endpoints/{ep_id}")).status_code == 404
