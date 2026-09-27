from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from src.api.deps import get_delivery_service, get_page_number_pagination_params
from src.core.pagination import PageNumberPaginationParams, PageNumberPaginationResponse
from src.core.security import AuthContext, get_auth_context_from_api_key
from src.models.delivery import WebhookDeliveryStatus
from src.schemas.delivery import (
    DeliveryAttemptListResponse,
    DeliveryListResponse,
    DeliveryRetrieveResponse,
    DeliveryRetryResponse,
)
from src.services.delivery import DeliveryService

router = APIRouter()


@router.get("", response_model=PageNumberPaginationResponse[DeliveryListResponse])
async def get_deliveries(
    request: Request,
    page_params: Annotated[PageNumberPaginationParams, Depends(get_page_number_pagination_params)],
    delivery_service: Annotated[DeliveryService, Depends(get_delivery_service)],
    auth: Annotated[AuthContext, Depends(get_auth_context_from_api_key)],
    event_id: str | None = None,
    endpoint_id: str | None = None,
    status: WebhookDeliveryStatus | None = None,
) -> PageNumberPaginationResponse[DeliveryListResponse]:
    """
    Get all deliveries.
    """
    return await delivery_service.list(
        owner_id=auth.owner_id,
        request=request,
        page_params=page_params,
        event_id=event_id,
        endpoint_id=endpoint_id,
        status=status,
    )


@router.get("/{delivery_id}", response_model=DeliveryRetrieveResponse)
async def get_delivery(
    delivery_id: UUID,
    delivery_service: Annotated[DeliveryService, Depends(get_delivery_service)],
    auth: Annotated[AuthContext, Depends(get_auth_context_from_api_key)],
) -> DeliveryRetrieveResponse:
    """
    Get a delivery by ID.
    """
    return await delivery_service.retrieve(delivery_id=delivery_id, owner_id=auth.owner_id)


@router.get(
    "/{delivery_id}/attempts",
    response_model=PageNumberPaginationResponse[DeliveryAttemptListResponse],
)
async def get_delivery_attempts(
    request: Request,
    delivery_id: UUID,
    delivery_service: Annotated[DeliveryService, Depends(get_delivery_service)],
    auth: Annotated[AuthContext, Depends(get_auth_context_from_api_key)],
) -> PageNumberPaginationResponse[DeliveryAttemptListResponse]:
    """
    Get all execution attempts for a delivery.
    """
    return await delivery_service.list_attempts(
        request=request,
        delivery_id=delivery_id,
        owner_id=auth.owner_id,
    )


@router.post(
    "/{delivery_id}/retry",
    response_model=DeliveryRetryResponse,
    status_code=status.HTTP_200_OK,
)
async def retry_delivery(
    delivery_id: UUID,
    delivery_service: Annotated[DeliveryService, Depends(get_delivery_service)],
    auth: Annotated[AuthContext, Depends(get_auth_context_from_api_key)],
) -> DeliveryRetryResponse:
    """
    Manually retry a dead-letter webhook delivery.
    Only deliveries in 'dead_letter' status can be retried.
    """
    return await delivery_service.retry(
        delivery_id=delivery_id,
        owner_id=auth.owner_id,
    )
