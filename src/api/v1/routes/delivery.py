from typing import Annotated

from fastapi import APIRouter, Depends, Request

from src.api.deps import get_delivery_service, get_page_number_pagination_params
from src.core.pagination import PageNumberPaginationParams, PageNumberPaginationResponse
from src.models.delivery import WebhookDeliveryStatus
from src.schemas.delivery import DeliveryListResponse, DeliveryRetrieveResponse
from src.services.delivery import DeliveryService

router = APIRouter()


@router.get("", response_model=PageNumberPaginationResponse[DeliveryListResponse])
async def get_deliveries(
    request: Request,
    page_params: Annotated[PageNumberPaginationParams, Depends(get_page_number_pagination_params)],
    delivery_service: Annotated[DeliveryService, Depends(get_delivery_service)],
    event_id: str | None = None,
    endpoint_id: str | None = None,
    status: WebhookDeliveryStatus | None = None,
) -> PageNumberPaginationResponse[DeliveryListResponse]:
    """
    Get all deliveries.
    """
    return await delivery_service.list(
        request=request,
        page_params=page_params,
        event_id=event_id,
        endpoint_id=endpoint_id,
        status=status,
    )


@router.get("/{delivery_id}", response_model=DeliveryRetrieveResponse)
async def get_delivery(
    delivery_id: str,
    delivery_service: Annotated[DeliveryService, Depends(get_delivery_service)],
) -> DeliveryRetrieveResponse:
    """
    Get a delivery by ID.
    """
    return await delivery_service.retrieve(delivery_id=delivery_id)
