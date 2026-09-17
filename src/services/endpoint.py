from fastapi import Request

from src.core.pagination import PageNumberPaginationParams, PageNumberPaginationResponse
from src.exceptions.endpoint import EndpointNotFoundError, EndpointValidationError
from src.repositories.endpoint import EndpointRepository
from src.schemas.endpoint import (
    EndpointCreateRequest,
    EndpointCreateResponse,
    EndpointListResponse,
    EndpointRetrieveResponse,
    EndpointUpdateRequest,
    EndpointUpdateResponse,
)
from src.utils.endpoint import validate_url


class EndpointService:
    def __init__(self, endpoint_repository: EndpointRepository | None = None):
        self.endpoint_repository = endpoint_repository or EndpointRepository()

    async def create(self, data: EndpointCreateRequest) -> EndpointCreateResponse:
        url = str(data.url)

        is_valid_url = validate_url(url)
        if not is_valid_url:
            raise EndpointValidationError("Invalid URL provided.")

        endpoint = await self.endpoint_repository.create(
            name=data.name,
            url=url,
            max_retries=data.max_retries,
        )

        return EndpointCreateResponse.model_validate(endpoint)

    async def retrieve(self, endpoint_id: str) -> EndpointRetrieveResponse:
        endpoint = await self.endpoint_repository.get_by_id(id=endpoint_id)
        if not endpoint:
            raise EndpointNotFoundError()

        return EndpointRetrieveResponse.model_validate(endpoint)

    async def list(
        self,
        request: Request,
        page_params: PageNumberPaginationParams,
    ) -> PageNumberPaginationResponse[EndpointListResponse]:
        total = await self.endpoint_repository.count()
        endpoints = await self.endpoint_repository.list(
            offset=page_params.offset,
            limit=page_params.limit,
        )
        return PageNumberPaginationResponse.build(
            request=request,
            total=total,
            page=page_params.page,
            page_size=page_params.page_size,
            items=[EndpointListResponse.model_validate(endpoint) for endpoint in endpoints],
        )

    async def update(self, endpoint_id: str, data: EndpointUpdateRequest) -> EndpointUpdateResponse:
        endpoint = await self.endpoint_repository.get_by_id(id=endpoint_id)
        if not endpoint:
            raise EndpointNotFoundError()

        update_data = data.model_dump(exclude_unset=True)
        if "url" in update_data:
            url = str(update_data["url"])
            is_valid_url = validate_url(url)
            if not is_valid_url:
                raise EndpointValidationError("Invalid URL provided.")
            update_data["url"] = url

        updated_endpoint = await self.endpoint_repository.update(
            endpoint=endpoint,
            data=update_data,
        )

        return EndpointUpdateResponse.model_validate(updated_endpoint)

    async def delete(self, endpoint_id: str) -> None:
        endpoint = await self.endpoint_repository.get_by_id(id=endpoint_id)
        if not endpoint:
            raise EndpointNotFoundError()

        await self.endpoint_repository.soft_delete(endpoint=endpoint)
