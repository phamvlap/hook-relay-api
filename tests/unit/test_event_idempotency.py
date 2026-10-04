"""Unit tests for Webhook Event idempotency and cross-tenant collision protection.

Validates:
1. Database unique partial index: (owner_id, idempotency_key) WHERE idempotency_key IS NOT NULL AND deleted_at IS NULL
2. Cross-tenant isolation: different tenants can safely use the same idempotency key
3. Soft-delete key reuse: soft-deleted events release the idempotency key for the tenant
4. Multiple NULL idempotency keys are allowed per tenant
5. EventRepository queries are strictly scoped by tenant
6. EventService idempotency retrieval and collision prevention
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.event import WebhookEvent, WebhookEventStatus
from src.models.owner import Owner
from src.repositories.delivery import DeliveryRepository
from src.repositories.endpoint import EndpointRepository, EndpointSecretRepository
from src.repositories.event import EventRepository
from src.schemas.event import EventCreateRequest
from src.services.event import EventService


@pytest.fixture
async def owner_a(db_session: AsyncSession) -> Owner:
    owner = Owner()
    db_session.add(owner)
    await db_session.flush()
    return owner


@pytest.fixture
async def owner_b(db_session: AsyncSession) -> Owner:
    owner = Owner()
    db_session.add(owner)
    await db_session.flush()
    return owner


# ---------------------------------------------------------------------------
# 1. Database Model & Unique Constraint Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_db_unique_constraint_blocks_same_tenant_duplicate_idempotency_key(
    db_session: AsyncSession,
    owner_a: Owner,
):
    """Ensures inserting two active events with the same idempotency_key for the same tenant raises IntegrityError."""
    shared_key = "idem_key_tenant_a_123"

    event_1 = WebhookEvent(
        owner_id=owner_a.id,
        event_type="test.event",
        payload={"msg": "first"},
        idempotency_key=shared_key,
        status=WebhookEventStatus.QUEUED,
    )
    db_session.add(event_1)
    await db_session.flush()

    event_2 = WebhookEvent(
        owner_id=owner_a.id,
        event_type="test.event",
        payload={"msg": "second"},
        idempotency_key=shared_key,
        status=WebhookEventStatus.QUEUED,
    )
    db_session.add(event_2)

    with pytest.raises(IntegrityError):
        await db_session.flush()

    await db_session.rollback()


@pytest.mark.asyncio
async def test_db_unique_constraint_allows_cross_tenant_same_idempotency_key(
    db_session: AsyncSession,
    owner_a: Owner,
    owner_b: Owner,
):
    """Ensures two different tenants can both use the exact same idempotency_key simultaneously without conflict."""
    shared_key = "cross_tenant_idem_key_456"

    event_a = WebhookEvent(
        owner_id=owner_a.id,
        event_type="tenant_a.event",
        payload={"tenant": "A"},
        idempotency_key=shared_key,
        status=WebhookEventStatus.QUEUED,
    )
    event_b = WebhookEvent(
        owner_id=owner_b.id,
        event_type="tenant_b.event",
        payload={"tenant": "B"},
        idempotency_key=shared_key,
        status=WebhookEventStatus.QUEUED,
    )

    db_session.add(event_a)
    db_session.add(event_b)
    # Both flush cleanly without raising IntegrityError
    await db_session.flush()

    assert event_a.id != event_b.id
    assert event_a.owner_id == owner_a.id
    assert event_b.owner_id == owner_b.id


@pytest.mark.asyncio
async def test_db_unique_constraint_allows_multiple_null_idempotency_keys(
    db_session: AsyncSession,
    owner_a: Owner,
):
    """Ensures multiple events with idempotency_key=None can be created for the same tenant without error."""
    event_1 = WebhookEvent(
        owner_id=owner_a.id,
        event_type="test.event",
        payload={"seq": 1},
        idempotency_key=None,
        status=WebhookEventStatus.QUEUED,
    )
    event_2 = WebhookEvent(
        owner_id=owner_a.id,
        event_type="test.event",
        payload={"seq": 2},
        idempotency_key=None,
        status=WebhookEventStatus.QUEUED,
    )

    db_session.add(event_1)
    db_session.add(event_2)
    await db_session.flush()

    assert event_1.id != event_2.id


@pytest.mark.asyncio
async def test_db_partial_index_allows_reuse_after_soft_delete(
    db_session: AsyncSession,
    owner_a: Owner,
):
    """Ensures the partial index (deleted_at IS NULL) allows a tenant to reuse an idempotency key after soft delete."""
    key = "reusable_key_after_delete"

    event_1 = WebhookEvent(
        owner_id=owner_a.id,
        event_type="test.event",
        payload={"ver": 1},
        idempotency_key=key,
        status=WebhookEventStatus.QUEUED,
    )
    db_session.add(event_1)
    await db_session.flush()

    # Soft delete event_1
    event_1.deleted_at = datetime.now(tz=UTC)
    await db_session.flush()

    # Re-insert new event with same key for the same tenant
    event_2 = WebhookEvent(
        owner_id=owner_a.id,
        event_type="test.event",
        payload={"ver": 2},
        idempotency_key=key,
        status=WebhookEventStatus.QUEUED,
    )
    db_session.add(event_2)
    await db_session.flush()

    assert event_1.id != event_2.id


# ---------------------------------------------------------------------------
# 2. Repository Scoping Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_repository_get_by_idempotency_key_tenant_isolated(
    db_session: AsyncSession,
    owner_a: Owner,
    owner_b: Owner,
):
    """Ensures EventRepository.get_by_idempotency_key only returns records matching the specified owner_id."""
    repo = EventRepository(session=db_session)
    shared_key = "repo_test_idem_key_789"

    event_a = await repo.create(
        owner_id=owner_a.id,
        event_type="order.created",
        payload={"owner": "A"},
        idempotency_key=shared_key,
    )
    await db_session.flush()

    # Query with Owner A -> returns event_a
    result_a = await repo.get_by_idempotency_key(idempotency_key=shared_key, owner_id=owner_a.id)
    assert result_a is not None
    assert result_a.id == event_a.id

    # Query with Owner B -> returns None (strictly tenant isolated)
    result_b = await repo.get_by_idempotency_key(idempotency_key=shared_key, owner_id=owner_b.id)
    assert result_b is None


@pytest.mark.asyncio
async def test_repository_get_by_idempotency_key_ignores_soft_deleted(
    db_session: AsyncSession,
    owner_a: Owner,
):
    """Ensures EventRepository.get_by_idempotency_key does not return soft-deleted events."""
    repo = EventRepository(session=db_session)
    key = "repo_soft_deleted_key"

    event = await repo.create(
        owner_id=owner_a.id,
        event_type="order.created",
        payload={"data": 1},
        idempotency_key=key,
    )
    await db_session.flush()

    # Soft delete the event
    event.deleted_at = datetime.now(tz=UTC)
    await db_session.flush()

    result = await repo.get_by_idempotency_key(idempotency_key=key, owner_id=owner_a.id)
    assert result is None


# ---------------------------------------------------------------------------
# 3. Service Layer Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_service_create_returns_existing_for_same_tenant(
    db_session: AsyncSession,
    owner_a: Owner,
):
    """Ensures EventService.create returns existing event when the same tenant reuses an idempotency key."""
    event_repo = EventRepository(session=db_session)
    endpoint_repo = EndpointRepository(session=db_session)
    delivery_repo = DeliveryRepository(session=db_session)
    secret_repo = EndpointSecretRepository(session=db_session)

    service = EventService(
        event_repository=event_repo,
        endpoint_repository=endpoint_repo,
        delivery_repository=delivery_repo,
        endpoint_secret_repository=secret_repo,
        session=db_session,
    )

    key = "service_idempotent_key_001"
    request_1 = EventCreateRequest(event_type="checkout.completed", payload={"cart_id": "c1"})

    res_1 = await service.create(data=request_1, idempotency_key=key, owner_id=owner_a.id)

    # Second call with same key and same owner
    request_2 = EventCreateRequest(event_type="checkout.different", payload={"cart_id": "c2"})
    res_2 = await service.create(data=request_2, idempotency_key=key, owner_id=owner_a.id)

    assert res_1.id == res_2.id
    assert res_2.event_type == "checkout.completed"


@pytest.mark.asyncio
async def test_service_create_allows_same_idempotency_key_for_different_tenant(
    db_session: AsyncSession,
    owner_a: Owner,
    owner_b: Owner,
):
    """Ensures EventService.create allows different tenants to use the same idempotency key without collision."""
    event_repo = EventRepository(session=db_session)
    endpoint_repo = EndpointRepository(session=db_session)
    delivery_repo = DeliveryRepository(session=db_session)
    secret_repo = EndpointSecretRepository(session=db_session)

    service = EventService(
        event_repository=event_repo,
        endpoint_repository=endpoint_repo,
        delivery_repository=delivery_repo,
        endpoint_secret_repository=secret_repo,
        session=db_session,
    )

    shared_key = "service_cross_tenant_shared_key_002"

    request_a = EventCreateRequest(event_type="tenant_a.action", payload={"val": "A"})
    res_a = await service.create(data=request_a, idempotency_key=shared_key, owner_id=owner_a.id)

    request_b = EventCreateRequest(event_type="tenant_b.action", payload={"val": "B"})
    res_b = await service.create(data=request_b, idempotency_key=shared_key, owner_id=owner_b.id)

    assert res_a.id != res_b.id
    assert res_a.event_type == "tenant_a.action"
    assert res_b.event_type == "tenant_b.action"
