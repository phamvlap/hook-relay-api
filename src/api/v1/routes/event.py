from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status

from src.api.deps import get_delivery_service, get_event_service, get_page_number_pagination_params
from src.core.context import AuthContext
from src.core.pagination import PageNumberPaginationParams, PageNumberPaginationResponse
from src.core.security import get_auth_context_from_api_key
from src.models.event import WebhookEventStatus
from src.schemas.delivery import DeliveryListInEvent
from src.schemas.event import (
    EventCreateRequest,
    EventCreateResponse,
    EventListResponse,
    EventRetrieveResponse,
)
from src.services.delivery import DeliveryService
from src.services.event import EventService

router = APIRouter()


@router.post("", response_model=EventCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_event(
    data: EventCreateRequest,
    event_service: Annotated[EventService, Depends(get_event_service)],
    auth: Annotated[AuthContext, Depends(get_auth_context_from_api_key)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> EventCreateResponse:
    """
    Create a new event.
    """
    return await event_service.create(
        data=data,
        idempotency_key=idempotency_key,
        owner_id=auth.owner_id,
    )


@router.get("", response_model=PageNumberPaginationResponse[EventListResponse])
async def list_events(
    request: Request,
    page_params: Annotated[PageNumberPaginationParams, Depends(get_page_number_pagination_params)],
    event_service: Annotated[EventService, Depends(get_event_service)],
    auth: Annotated[AuthContext, Depends(get_auth_context_from_api_key)],
    status: WebhookEventStatus | None = None,
) -> PageNumberPaginationResponse[EventListResponse]:
    """
    List all events.
    """
    return await event_service.list(
        owner_id=auth.owner_id,
        request=request,
        page_params=page_params,
        status=status,
    )


@router.get("/{event_id}", response_model=EventRetrieveResponse)
async def retrieve_event(
    event_id: UUID,
    event_service: Annotated[EventService, Depends(get_event_service)],
    auth: Annotated[AuthContext, Depends(get_auth_context_from_api_key)],
) -> EventRetrieveResponse:
    """
    Retrieve an event by its ID.
    """
    return await event_service.retrieve(event_id=event_id, owner_id=auth.owner_id)


@router.get(
    "/{event_id}/deliveries",
    response_model=PageNumberPaginationResponse[DeliveryListInEvent],
)
async def list_deliveries_in_event(
    event_id: UUID,
    request: Request,
    page_params: Annotated[PageNumberPaginationParams, Depends(get_page_number_pagination_params)],
    delivery_service: Annotated[DeliveryService, Depends(get_delivery_service)],
    auth: Annotated[AuthContext, Depends(get_auth_context_from_api_key)],
) -> PageNumberPaginationResponse[DeliveryListInEvent]:
    """
    List all deliveries associated with a specific event.
    """
    return await delivery_service.list_by_event(
        owner_id=auth.owner_id,
        event_id=event_id,
        request=request,
        page_params=page_params,
    )
