from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status

from src.api.deps import get_endpoint_service, get_page_number_pagination_params
from src.core.pagination import PageNumberPaginationParams, PageNumberPaginationResponse
from src.core.security import AuthContext, get_auth_context_from_api_key
from src.schemas.endpoint import (
    EndpointCreateRequest,
    EndpointCreateResponse,
    EndpointListResponse,
    EndpointRetrieveResponse,
    EndpointUpdateRequest,
    EndpointUpdateResponse,
)
from src.services.endpoint import EndpointService

router = APIRouter()


@router.get("", response_model=PageNumberPaginationResponse[EndpointListResponse])
async def get_endpoints(
    request: Request,
    page_params: Annotated[PageNumberPaginationParams, Depends(get_page_number_pagination_params)],
    endpoint_service: Annotated[EndpointService, Depends(get_endpoint_service)],
    auth: Annotated[AuthContext, Depends(get_auth_context_from_api_key)],
) -> PageNumberPaginationResponse[EndpointListResponse]:
    """
    Get all endpoints.
    """
    return await endpoint_service.list(
        request=request,
        page_params=page_params,
        owner_id=auth.owner_id,
    )


@router.post("", response_model=EndpointCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_endpoint(
    data: EndpointCreateRequest,
    endpoint_service: Annotated[EndpointService, Depends(get_endpoint_service)],
    auth: Annotated[AuthContext, Depends(get_auth_context_from_api_key)],
) -> EndpointCreateResponse:
    """
    Create a new endpoint.
    """
    return await endpoint_service.create(data=data, owner_id=auth.owner_id)


@router.get("/{endpoint_id}", response_model=EndpointRetrieveResponse)
async def get_endpoint(
    endpoint_id: UUID,
    endpoint_service: Annotated[EndpointService, Depends(get_endpoint_service)],
    auth: Annotated[AuthContext, Depends(get_auth_context_from_api_key)],
) -> EndpointRetrieveResponse:
    """
    Get an endpoint by ID.
    """
    return await endpoint_service.retrieve(endpoint_id=endpoint_id, owner_id=auth.owner_id)


@router.patch("/{endpoint_id}", response_model=EndpointUpdateResponse)
async def update_endpoint(
    endpoint_id: UUID,
    data: EndpointUpdateRequest,
    endpoint_service: Annotated[EndpointService, Depends(get_endpoint_service)],
    auth: Annotated[AuthContext, Depends(get_auth_context_from_api_key)],
) -> EndpointUpdateResponse:
    """
    Update an endpoint by ID.
    """
    return await endpoint_service.update(endpoint_id=endpoint_id, data=data, owner_id=auth.owner_id)


@router.delete("/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_endpoint(
    endpoint_id: UUID,
    endpoint_service: Annotated[EndpointService, Depends(get_endpoint_service)],
    auth: Annotated[AuthContext, Depends(get_auth_context_from_api_key)],
) -> Response:
    """
    Delete an endpoint by ID.
    """
    await endpoint_service.delete(endpoint_id=endpoint_id, owner_id=auth.owner_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
