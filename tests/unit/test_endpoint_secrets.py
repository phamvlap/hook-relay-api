"""Unit tests for EndpointSecretRepository batch operations and N+1 prevention."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.endpoint import (
    WebhookEndpoint,
    WebhookEndpointSecret,
    WebhookEndpointSecretStatus,
    WebhookEndpointStatus,
)
from src.models.event import WebhookEventStatus
from src.models.owner import Owner
from src.repositories.delivery import DeliveryRepository
from src.repositories.endpoint import EndpointRepository, EndpointSecretRepository
from src.repositories.event import EventRepository
from src.schemas.event import EventCreateRequest
from src.services.event import EventService


@pytest.fixture
async def sample_owner(db_session: AsyncSession) -> Owner:
    owner = Owner()
    db_session.add(owner)
    await db_session.flush()
    return owner


@pytest.mark.asyncio
async def test_get_active_secrets_by_endpoint_ids_empty_input_returns_empty_dict(
    db_session: AsyncSession,
):
    """Empty list of endpoint IDs immediately returns an empty mapping without database query."""
    repo = EndpointSecretRepository(session=db_session)
    result = await repo.get_active_secrets_by_endpoint_ids(endpoint_ids=[])
    assert result == {}


@pytest.mark.asyncio
async def test_get_active_secrets_by_endpoint_ids_batch_resolution(
    db_session: AsyncSession,
    sample_owner: Owner,
):
    """Verifies single batch lookup resolves the active secret for multiple endpoints."""
    repo = EndpointSecretRepository(session=db_session)

    # 1. Create 3 endpoints
    ep1 = WebhookEndpoint(name="EP1", url="https://example.com/1", owner_id=sample_owner.id)
    ep2 = WebhookEndpoint(name="EP2", url="https://example.com/2", owner_id=sample_owner.id)
    ep3 = WebhookEndpoint(name="EP3", url="https://example.com/3", owner_id=sample_owner.id)
    db_session.add_all([ep1, ep2, ep3])
    await db_session.flush()

    # 2. Add secrets:
    # EP1 has single active secret (v1)
    s1 = WebhookEndpointSecret(
        endpoint_id=ep1.id,
        encrypted_secret="enc_s1",
        version=1,
        status=WebhookEndpointSecretStatus.ACTIVE,
    )
    # EP2 has revoked secret (v1) and active secret (v2)
    s2_old = WebhookEndpointSecret(
        endpoint_id=ep2.id,
        encrypted_secret="enc_s2_old",
        version=1,
        status=WebhookEndpointSecretStatus.REVOKED,
    )
    s2_new = WebhookEndpointSecret(
        endpoint_id=ep2.id,
        encrypted_secret="enc_s2_new",
        version=2,
        status=WebhookEndpointSecretStatus.ACTIVE,
    )
    # EP3 has no secrets at all
    db_session.add_all([s1, s2_old, s2_new])
    await db_session.flush()

    # 3. Batch query
    secrets_map = await repo.get_active_secrets_by_endpoint_ids(
        endpoint_ids=[ep1.id, ep2.id, ep3.id],
    )

    # Asserts
    assert ep1.id in secrets_map
    assert secrets_map[ep1.id].version == 1
    assert secrets_map[ep1.id].encrypted_secret == "enc_s1"

    assert ep2.id in secrets_map
    assert secrets_map[ep2.id].version == 2
    assert secrets_map[ep2.id].encrypted_secret == "enc_s2_new"

    # EP3 has no secret
    assert ep3.id not in secrets_map


@pytest.mark.asyncio
async def test_get_active_secrets_by_endpoint_ids_ignores_soft_deleted(
    db_session: AsyncSession,
    sample_owner: Owner,
):
    """Ensures soft-deleted active secrets are excluded from batch lookup."""
    repo = EndpointSecretRepository(session=db_session)

    ep = WebhookEndpoint(name="EP", url="https://example.com/ep", owner_id=sample_owner.id)
    db_session.add(ep)
    await db_session.flush()

    s = WebhookEndpointSecret(
        endpoint_id=ep.id,
        encrypted_secret="enc_deleted",
        version=1,
        status=WebhookEndpointSecretStatus.ACTIVE,
        deleted_at=datetime.now(tz=UTC),
    )
    db_session.add(s)
    await db_session.flush()

    secrets_map = await repo.get_active_secrets_by_endpoint_ids(endpoint_ids=[ep.id])
    assert ep.id not in secrets_map


@pytest.mark.asyncio
async def test_event_service_ingestion_uses_batch_lookup_not_n_plus_1(mocker):
    """Verifies that EventService.create invokes get_active_secrets_by_endpoint_ids once instead of get_active_secret N times."""
    mock_event_repo = MagicMock(spec=EventRepository)
    mock_endpoint_repo = MagicMock(spec=EndpointRepository)
    mock_secret_repo = MagicMock(spec=EndpointSecretRepository)
    mock_delivery_repo = MagicMock(spec=DeliveryRepository)
    mock_session = MagicMock(spec=AsyncSession)

    # Setup session begin_nested and commit context managers
    nested_cm = MagicMock()
    nested_cm.__aenter__ = AsyncMock(return_value=None)
    nested_cm.__aexit__ = AsyncMock(return_value=None)
    mock_session.begin_nested.return_value = nested_cm
    mock_session.commit = AsyncMock()

    owner_id = uuid4()
    ep1_id = uuid4()
    ep2_id = uuid4()
    ep3_id = uuid4()

    ep1 = MagicMock(id=ep1_id, status=WebhookEndpointStatus.ACTIVE)
    ep2 = MagicMock(id=ep2_id, status=WebhookEndpointStatus.ACTIVE)
    ep3 = MagicMock(id=ep3_id, status=WebhookEndpointStatus.ACTIVE)

    mock_endpoint_repo.list = AsyncMock(return_value=[ep1, ep2, ep3])
    fake_event = MagicMock(
        id=uuid4(),
        event_type="test.event",
        payload={"key": "value"},
        status=WebhookEventStatus.QUEUED,
        created_at=datetime.now(tz=UTC),
    )
    mock_event_repo.create = AsyncMock(return_value=fake_event)
    mock_delivery_repo.bulk_create = AsyncMock()

    # Secret repo mock
    secret_ep1 = MagicMock(version=2)
    mock_secret_repo.get_active_secrets_by_endpoint_ids = AsyncMock(
        return_value={ep1_id: secret_ep1}
    )
    mock_secret_repo.get_active_secret = AsyncMock()

    mocker.patch("src.services.event.deliver_webhook_task.delay")

    service = EventService(
        event_repository=mock_event_repo,
        endpoint_repository=mock_endpoint_repo,
        delivery_repository=mock_delivery_repo,
        endpoint_secret_repository=mock_secret_repo,
        session=mock_session,
    )

    request_data = EventCreateRequest(event_type="test.event", payload={"key": "value"})
    await service.create(data=request_data, owner_id=owner_id)

    # Crucial assertion: get_active_secrets_by_endpoint_ids was called exactly ONCE
    assert mock_secret_repo.get_active_secrets_by_endpoint_ids.call_count == 1
    call_args = mock_secret_repo.get_active_secrets_by_endpoint_ids.call_args[1]
    assert call_args["endpoint_ids"] == [ep1_id, ep2_id, ep3_id]

    # And sequential get_active_secret was NEVER called
    assert mock_secret_repo.get_active_secret.call_count == 0

    # Bulk create was called with 3 deliveries
    assert mock_delivery_repo.bulk_create.call_count == 1
    deliveries_arg = mock_delivery_repo.bulk_create.call_args[1]["deliveries"]
    assert len(deliveries_arg) == 3
    # ep1 got secret_version 2, ep2 and ep3 defaulted to 1
    assert deliveries_arg[0].secret_version == 2
    assert deliveries_arg[1].secret_version == 1
    assert deliveries_arg[2].secret_version == 1
