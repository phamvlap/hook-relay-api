"""Integration tests for DeliveryRepository queries and concurrency locks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.delivery import WebhookDelivery, WebhookDeliveryStatus
from src.models.endpoint import WebhookEndpoint, WebhookEndpointStatus
from src.models.event import WebhookEvent
from src.models.owner import Owner
from src.repositories.delivery import DeliveryRepository


@pytest.mark.integration
class TestDeliveryRepositoryStuckDeliveries:
    async def test_get_stuck_deliveries_for_update_filtering(
        self,
        db_session: AsyncSession,
        test_owner: Owner,
    ):
        """Verifies get_stuck_deliveries_for_update only returns delivering items older than threshold."""
        repo = DeliveryRepository(db_session)

        # 1. Create Endpoint & Event
        endpoint = WebhookEndpoint(
            owner_id=test_owner.id,
            name="Test EP",
            url="https://example.com/webhook",
            status=WebhookEndpointStatus.ACTIVE,
        )
        event = WebhookEvent(
            owner_id=test_owner.id,
            event_type="order.placed",
            payload={"id": 1},
        )
        db_session.add_all([endpoint, event])
        await db_session.flush()

        # 2. Create deliveries with varying statuses
        # D1: Stuck in DELIVERING (10 min old) -> SHOULD BE RETURNED
        d1 = WebhookDelivery(
            event_id=event.id,
            endpoint_id=endpoint.id,
            owner_id=test_owner.id,
            secret_version=1,
            status=WebhookDeliveryStatus.DELIVERING,
        )
        # D2: DELIVERING but RECENT (30 seconds old) -> SHOULD NOT BE RETURNED
        d2 = WebhookDelivery(
            event_id=event.id,
            endpoint_id=endpoint.id,
            owner_id=test_owner.id,
            secret_version=1,
            status=WebhookDeliveryStatus.DELIVERING,
        )
        # D3: QUEUED (10 min old) -> SHOULD NOT BE RETURNED
        d3 = WebhookDelivery(
            event_id=event.id,
            endpoint_id=endpoint.id,
            owner_id=test_owner.id,
            secret_version=1,
            status=WebhookDeliveryStatus.QUEUED,
        )
        # D4: SUCCESS (10 min old) -> SHOULD NOT BE RETURNED
        d4 = WebhookDelivery(
            event_id=event.id,
            endpoint_id=endpoint.id,
            owner_id=test_owner.id,
            secret_version=1,
            status=WebhookDeliveryStatus.SUCCESS,
        )
        db_session.add_all([d1, d2, d3, d4])
        await db_session.flush()

        # Update updated_at timestamps explicitly
        old_time = datetime.now(tz=UTC) - timedelta(minutes=10)
        recent_time = datetime.now(tz=UTC) - timedelta(seconds=30)

        await db_session.execute(
            # pyrefly: ignore [unexpected-keyword]
            update(WebhookDelivery).where(WebhookDelivery.id == d1.id).values(updated_at=old_time)
        )
        await db_session.execute(
            update(WebhookDelivery)
            .where(WebhookDelivery.id == d2.id)
            # pyrefly: ignore [unexpected-keyword]
            .values(updated_at=recent_time)
        )
        await db_session.execute(
            # pyrefly: ignore [unexpected-keyword]
            update(WebhookDelivery).where(WebhookDelivery.id == d3.id).values(updated_at=old_time)
        )
        await db_session.execute(
            # pyrefly: ignore [unexpected-keyword]
            update(WebhookDelivery).where(WebhookDelivery.id == d4.id).values(updated_at=old_time)
        )
        await db_session.flush()

        # 3. Query stuck deliveries older than 5 minutes
        threshold = datetime.now(tz=UTC) - timedelta(minutes=5)
        stuck = await repo.get_stuck_deliveries_for_update(stuck_before=threshold, limit=10)

        # 4. Verify only d1 is returned
        stuck_ids = [d.id for d in stuck]
        assert d1.id in stuck_ids
        assert d2.id not in stuck_ids
        assert d3.id not in stuck_ids
        assert d4.id not in stuck_ids

    async def test_get_stuck_deliveries_respects_limit(
        self,
        db_session: AsyncSession,
        test_owner: Owner,
    ):
        """Verifies limit parameter is respected."""
        repo = DeliveryRepository(db_session)

        endpoint = WebhookEndpoint(
            owner_id=test_owner.id,
            name="Test EP 2",
            url="https://example.com/webhook2",
            status=WebhookEndpointStatus.ACTIVE,
        )
        event = WebhookEvent(
            owner_id=test_owner.id,
            event_type="order.placed",
            payload={"id": 2},
        )
        db_session.add_all([endpoint, event])
        await db_session.flush()

        deliveries = []
        for _ in range(5):
            d = WebhookDelivery(
                event_id=event.id,
                endpoint_id=endpoint.id,
                owner_id=test_owner.id,
                secret_version=1,
                status=WebhookDeliveryStatus.DELIVERING,
            )
            deliveries.append(d)

        db_session.add_all(deliveries)
        await db_session.flush()

        old_time = datetime.now(tz=UTC) - timedelta(minutes=15)
        for d in deliveries:
            await db_session.execute(
                update(WebhookDelivery)
                .where(WebhookDelivery.id == d.id)
                # pyrefly: ignore [unexpected-keyword]
                .values(updated_at=old_time)
            )
        await db_session.flush()

        threshold = datetime.now(tz=UTC) - timedelta(minutes=5)
        stuck = await repo.get_stuck_deliveries_for_update(stuck_before=threshold, limit=2)

        assert len(stuck) == 2
