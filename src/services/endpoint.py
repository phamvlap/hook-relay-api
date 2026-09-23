import ipaddress
import socket
from urllib.parse import urlparse
from uuid import UUID

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.core.pagination import PageNumberPaginationParams, PageNumberPaginationResponse
from src.exceptions.endpoint import (
    EndpointConflictError,
    EndpointNotFoundError,
    EndpointValidationError,
)
from src.models.endpoint import WebhookEndpointStatus
from src.repositories.endpoint import EndpointRepository
from src.schemas.endpoint import (
    EndpointCreateRequest,
    EndpointCreateResponse,
    EndpointListResponse,
    EndpointPauseResponse,
    EndpointResumeResponse,
    EndpointRetrieveResponse,
    EndpointUpdateRequest,
    EndpointUpdateResponse,
)


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

        # Validate the URL format and safety
        validate_safe_webhook_url(url)

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
            raise EndpointConflictError("An endpoint with the same URL already exists.")

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
        status: WebhookEndpointStatus | None = None,
    ) -> PageNumberPaginationResponse[EndpointListResponse]:
        total = await self.endpoint_repository.count(owner_id=owner_id, status=status)
        endpoints = await self.endpoint_repository.list(
            owner_id=owner_id,
            offset=page_params.offset,
            limit=page_params.limit,
            status=status,
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

            # Validate the URL format and safety
            validate_safe_webhook_url(url)

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
            raise EndpointConflictError("An endpoint with the same URL already exists.")

        except Exception:
            self.session.rollback()
            raise

    async def delete(self, *, endpoint_id: str | UUID, owner_id: str | UUID) -> None:
        endpoint = await self.endpoint_repository.get_by_id(id=endpoint_id, owner_id=owner_id)
        if not endpoint:
            raise EndpointNotFoundError()

        await self.endpoint_repository.soft_delete(endpoint=endpoint)
        self.session.commit()

    async def pause(
        self,
        *,
        endpoint_id: str | UUID,
        owner_id: str | UUID,
    ) -> EndpointPauseResponse:
        endpoint = await self.endpoint_repository.get_by_id(id=endpoint_id, owner_id=owner_id)
        if not endpoint:
            raise EndpointNotFoundError()

        try:
            with self.session.begin_nested():
                await self.endpoint_repository.update(
                    endpoint=endpoint,
                    data={"status": WebhookEndpointStatus.PAUSED},
                )

            self.session.commit()
            return EndpointPauseResponse(success=True)

        except Exception:
            self.session.rollback()
            raise

    async def resume(
        self,
        *,
        endpoint_id: str | UUID,
        owner_id: str | UUID,
    ) -> EndpointResumeResponse:
        endpoint = await self.endpoint_repository.get_by_id(id=endpoint_id, owner_id=owner_id)
        if not endpoint:
            raise EndpointNotFoundError()

        try:
            with self.session.begin_nested():
                await self.endpoint_repository.update(
                    endpoint=endpoint,
                    data={"status": WebhookEndpointStatus.ACTIVE},
                )

            self.session.commit()
            return EndpointResumeResponse(success=True)

        except Exception:
            self.session.rollback()
            raise


def validate_safe_webhook_url(url: str) -> None:
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise EndpointValidationError(
            "Webhook URL must have a valid scheme (http or https) and a valid host."
        )

    if not parsed.hostname:
        raise EndpointValidationError("Webhook URL must have a valid host.")

    try:
        ip = ipaddress.ip_address(parsed.hostname)
        if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
            raise EndpointValidationError(
                "Webhook URL must not point to a private, loopback, reserved, or link-local IP address."
            )

    except (socket.gaierror, ValueError):
        pass
