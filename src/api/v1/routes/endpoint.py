from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from src.api.deps import get_endpoint_service, get_page_number_pagination_params
from src.core.pagination import PageNumberPaginationParams, PageNumberPaginationResponse
from src.schemas.endpoint import (
    EndpointCreateRequest,
    EndpointCreateResponse,
    EndpointListResponse,
    EndpointRetrieveResponse,
)
from src.services.endpoint import EndpointService

router = APIRouter()


@router.get("", response_model=PageNumberPaginationResponse[EndpointListResponse])
async def get_endpoints(
    request: Request,
    page_params: Annotated[PageNumberPaginationParams, Depends(get_page_number_pagination_params)],
    endpoint_service: Annotated[EndpointService, Depends(get_endpoint_service)],
) -> PageNumberPaginationResponse[EndpointListResponse]:
    """
    Get all endpoints.
    """
    return await endpoint_service.list(request=request, page_params=page_params)


@router.post("", response_model=EndpointCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_endpoint(
    data: EndpointCreateRequest,
    endpoint_service: Annotated[EndpointService, Depends(get_endpoint_service)],
) -> EndpointCreateResponse:
    """
    Create a new endpoint.
    """
    return await endpoint_service.create(data)


@router.get("/{endpoint_id}", response_model=EndpointRetrieveResponse)
async def get_endpoint(
    endpoint_id: str,
    endpoint_service: Annotated[EndpointService, Depends(get_endpoint_service)],
) -> EndpointRetrieveResponse:
    """
    Get an endpoint by ID.
    """
    return await endpoint_service.retrieve(endpoint_id)


@router.put("/{endpoint_id}")
async def update_endpoint(endpoint_id: str):
    """
    Update an endpoint by ID.
    """
    return {"message": f"Update endpoint with ID {endpoint_id}."}


@router.delete("/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_endpoint(endpoint_id: str):
    """
    Delete an endpoint by ID.
    """
    return {"message": f"Delete endpoint with ID {endpoint_id}."}
