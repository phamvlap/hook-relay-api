from uuid import UUID

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
    def __init__(self, endpoint_repository: EndpointRepository, session: Session) -> None:
        self.endpoint_repository = endpoint_repository
        self.session = session

    async def create(
        self,
        *,
        data: EndpointCreateRequest,
        owner_id: str | UUID,
    ) -> EndpointCreateResponse:
        url = str(data.url)

        is_valid_url = validate_url(url)
        if not is_valid_url:
            raise EndpointValidationError("Invalid URL provided.")

        try:
            with self.session.begin_nested():
                endpoint = await self.endpoint_repository.create(
                    name=data.name,
                    url=url,
                    max_retries=data.max_retries,
                    owner_id=owner_id,
                )

            self.session.commit()
            return EndpointCreateResponse.model_validate(endpoint)

        except IntegrityError:
            self.session.rollback()
            raise

        except Exception:
            self.session.rollback()
            raise

    async def retrieve(
        self,
        *,
        endpoint_id: str | UUID,
        owner_id: str | UUID,
    ) -> EndpointRetrieveResponse:
        endpoint = await self.endpoint_repository.get_by_id(id=endpoint_id, owner_id=owner_id)
        if not endpoint:
            raise EndpointNotFoundError()

        return EndpointRetrieveResponse.model_validate(endpoint)

    async def list(
        self,
        *,
        owner_id: str | UUID,
        request: Request,
        page_params: PageNumberPaginationParams,
    ) -> PageNumberPaginationResponse[EndpointListResponse]:
        total = await self.endpoint_repository.count(owner_id=owner_id)
        endpoints = await self.endpoint_repository.list(
            owner_id=owner_id,
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

    async def update(
        self,
        *,
        endpoint_id: str | UUID,
        owner_id: str | UUID,
        data: EndpointUpdateRequest,
    ) -> EndpointUpdateResponse:
        endpoint = await self.endpoint_repository.get_by_id(id=endpoint_id, owner_id=owner_id)
        if not endpoint:
            raise EndpointNotFoundError()

        update_data = data.model_dump(exclude_unset=True)
        if "url" in update_data and update_data["url"] is not None:
            url = str(update_data["url"])
            is_valid_url = validate_url(url)
            if not is_valid_url:
                raise EndpointValidationError("Invalid URL provided.")
            update_data["url"] = url

        try:
            with self.session.begin_nested():
                updated_endpoint = await self.endpoint_repository.update(
                    endpoint=endpoint,
                    data=update_data,
                )

            self.session.commit()
            return EndpointUpdateResponse.model_validate(updated_endpoint)

        except IntegrityError:
            self.session.rollback()
            raise

        except Exception:
            self.session.rollback()
            raise

    async def delete(self, *, endpoint_id: str | UUID, owner_id: str | UUID) -> None:
        endpoint = await self.endpoint_repository.get_by_id(id=endpoint_id, owner_id=owner_id)
        if not endpoint:
            raise EndpointNotFoundError()

        await self.endpoint_repository.soft_delete(endpoint=endpoint)
        self.session.commit()
