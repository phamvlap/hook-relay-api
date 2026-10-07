from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.pagination import PageNumberPaginationParams
from src.database.session import AsyncLocalSession
from src.repositories.delivery import DeliveryAttemptRepository, DeliveryRepository
from src.repositories.endpoint import EndpointRepository, EndpointSecretRepository
from src.repositories.event import EventRepository
from src.services.delivery import DeliveryService
from src.services.endpoint import EndpointService
from src.services.event import EventService


async def get_db() -> AsyncGenerator[AsyncSession]:
    session: AsyncSession = AsyncLocalSession()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


SessionDep = Annotated[AsyncSession, Depends(get_db)]


def get_endpoint_repository(session: SessionDep) -> EndpointRepository:
    return EndpointRepository(session=session)


def get_endpoint_secret_repository(session: SessionDep) -> EndpointSecretRepository:
    return EndpointSecretRepository(session=session)


def get_delivery_repository(session: SessionDep) -> DeliveryRepository:
    return DeliveryRepository(session=session)


def get_delivery_attempt_repository(session: SessionDep) -> DeliveryAttemptRepository:
    return DeliveryAttemptRepository(session=session)


def get_event_repository(session: SessionDep) -> EventRepository:
    return EventRepository(session=session)


def get_endpoint_service(
    session: SessionDep,
    endpoint_repository: Annotated[EndpointRepository, Depends(get_endpoint_repository)],
    endpoint_secret_repository: Annotated[
        EndpointSecretRepository,
        Depends(get_endpoint_secret_repository),
    ],
) -> EndpointService:
    return EndpointService(
        endpoint_repository=endpoint_repository,
        endpoint_secret_repository=endpoint_secret_repository,
        session=session,
    )


def get_delivery_service(
    session: SessionDep,
    event_repository: Annotated[EventRepository, Depends(get_event_repository)],
    endpoint_repository: Annotated[EndpointRepository, Depends(get_endpoint_repository)],
    delivery_repository: Annotated[DeliveryRepository, Depends(get_delivery_repository)],
    delivery_attempt_repository: Annotated[
        DeliveryAttemptRepository,
        Depends(get_delivery_attempt_repository),
    ],
    endpoint_secret_repository: Annotated[
        EndpointSecretRepository,
        Depends(get_endpoint_secret_repository),
    ],
) -> DeliveryService:
    return DeliveryService(
        session=session,
        event_repository=event_repository,
        endpoint_repository=endpoint_repository,
        delivery_repository=delivery_repository,
        delivery_attempt_repository=delivery_attempt_repository,
        endpoint_secret_repository=endpoint_secret_repository,
    )


def get_event_service(
    session: SessionDep,
    event_repository: Annotated[EventRepository, Depends(get_event_repository)],
    endpoint_repository: Annotated[EndpointRepository, Depends(get_endpoint_repository)],
    delivery_repository: Annotated[DeliveryRepository, Depends(get_delivery_repository)],
    endpoint_secret_repository: Annotated[
        EndpointSecretRepository,
        Depends(get_endpoint_secret_repository),
    ],
) -> EventService:
    return EventService(
        session=session,
        event_repository=event_repository,
        endpoint_repository=endpoint_repository,
        delivery_repository=delivery_repository,
        endpoint_secret_repository=endpoint_secret_repository,
    )


def get_page_number_pagination_params(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> PageNumberPaginationParams:
    return PageNumberPaginationParams(page=page, page_size=page_size)


# Rate limit dependencies
from src.core.rate_limit.limiter import (
    RateLimitIngestDep,
    RateLimitPublicDep,
    RateLimitReadsDep,
    RateLimitSensitiveDep,
    RateLimitWritesDep,
)

__all__ = [
    "RateLimitIngestDep",
    "RateLimitPublicDep",
    "RateLimitReadsDep",
    "RateLimitSensitiveDep",
    "RateLimitWritesDep",
]
