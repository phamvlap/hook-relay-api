import ipaddress
import socket
from urllib.parse import urlparse
from uuid import UUID

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.pagination import PageNumberPaginationParams, PageNumberPaginationResponse
from src.core.ssrf import is_hostname_local, is_ip_allowed
from src.exceptions.endpoint import (
    EndpointConflictError,
    EndpointNotFoundError,
    EndpointSecretConflictError,
    EndpointValidationError,
)
from src.models.endpoint import WebhookEndpointStatus
from src.repositories.endpoint import EndpointRepository, EndpointSecretRepository
from src.schemas.endpoint import (
    EndpointCreateRequest,
    EndpointCreateResponse,
    EndpointListResponse,
    EndpointPauseResponse,
    EndpointResumeResponse,
    EndpointRetrieveResponse,
    EndpointRotateSecretResponse,
    EndpointUpdateRequest,
    EndpointUpdateResponse,
)
from src.utils.endpoint import EndpointSecretCrypto


class EndpointService:
    def __init__(
        self,
        endpoint_repository: EndpointRepository,
        endpoint_secret_repository: EndpointSecretRepository,
        session: AsyncSession,
    ) -> None:
        self.endpoint_repository = endpoint_repository
        self.endpoint_secret_repository = endpoint_secret_repository
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
            async with self.session.begin_nested():
                endpoint = await self.endpoint_repository.create(
                    name=data.name,
                    url=url,
                    max_retries=data.max_retries,
                    owner_id=owner_id,
                )

                endpoint_secret_crypto = EndpointSecretCrypto()

                # Generate initial secret and encrypt it with EndpointSecretCrypto
                raw_secret = endpoint_secret_crypto.generate_secret()
                encrypted_secret = endpoint_secret_crypto.encrypt(raw_secret)

                await self.endpoint_secret_repository.create(
                    endpoint_id=endpoint.id,
                    encrypted_secret=encrypted_secret,
                    version=1,
                )

            await self.session.commit()
            return EndpointCreateResponse(
                id=endpoint.id,
                name=endpoint.name,
                url=endpoint.url,
                status=endpoint.status,
                max_retries=endpoint.max_retries,
                secret=raw_secret,
                secret_version=1,
                created_at=endpoint.created_at,
            )

        except IntegrityError:
            await self.session.rollback()
            raise EndpointConflictError("An endpoint with the same URL already exists.")

        except Exception:
            await self.session.rollback()
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

        request_data = data.model_dump(exclude_unset=True)
        update_data = {k: v for k, v in request_data.items() if getattr(endpoint, k, None) != v}

        if not update_data:
            return EndpointUpdateResponse.model_validate(endpoint)

        if "url" in update_data and update_data["url"] is not None:
            url = str(update_data["url"])

            # Validate the URL format and safety
            validate_safe_webhook_url(url)

            update_data["url"] = url

        try:
            async with self.session.begin_nested():
                updated_endpoint = await self.endpoint_repository.update(
                    endpoint=endpoint,
                    data=update_data,
                )

            await self.session.commit()
            return EndpointUpdateResponse.model_validate(updated_endpoint)

        except IntegrityError:
            await self.session.rollback()
            raise EndpointConflictError("An endpoint with the same URL already exists.")

        except Exception:
            await self.session.rollback()
            raise

    async def delete(self, *, endpoint_id: str | UUID, owner_id: str | UUID) -> None:
        endpoint = await self.endpoint_repository.get_by_id(id=endpoint_id, owner_id=owner_id)
        if not endpoint:
            raise EndpointNotFoundError()

        await self.endpoint_repository.soft_delete(endpoint=endpoint)
        await self.session.commit()

    async def pause(
        self,
        *,
        endpoint_id: str | UUID,
        owner_id: str | UUID,
    ) -> EndpointPauseResponse:
        endpoint = await self.endpoint_repository.get_by_id(id=endpoint_id, owner_id=owner_id)
        if not endpoint:
            raise EndpointNotFoundError()

        if endpoint.status == WebhookEndpointStatus.PAUSED:
            return EndpointPauseResponse(success=True)

        try:
            async with self.session.begin_nested():
                await self.endpoint_repository.update(
                    endpoint=endpoint,
                    data={"status": WebhookEndpointStatus.PAUSED},
                )

            await self.session.commit()
            return EndpointPauseResponse(success=True)

        except Exception:
            await self.session.rollback()
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

        if endpoint.status == WebhookEndpointStatus.ACTIVE:
            return EndpointResumeResponse(success=True)

        try:
            async with self.session.begin_nested():
                await self.endpoint_repository.update(
                    endpoint=endpoint,
                    data={"status": WebhookEndpointStatus.ACTIVE},
                )

            await self.session.commit()
            return EndpointResumeResponse(success=True)

        except Exception:
            await self.session.rollback()
            raise

    async def rotate_secret(
        self,
        *,
        endpoint_id: str | UUID,
        owner_id: str | UUID,
    ) -> EndpointRotateSecretResponse:
        endpoint = await self.endpoint_repository.get_by_id(id=endpoint_id, owner_id=owner_id)
        if not endpoint:
            raise EndpointNotFoundError()

        try:
            async with self.session.begin_nested():
                next_version = await self.endpoint_secret_repository.get_next_version(
                    endpoint_id=endpoint.id,
                )

                # Revoke existing active secret(s)
                await self.endpoint_secret_repository.revoke_active_secrets(
                    endpoint_id=endpoint.id,
                )

                endpoint_secret_crypto = EndpointSecretCrypto()

                # Generate new secret and encrypt
                raw_secret = endpoint_secret_crypto.generate_secret()
                encrypted_secret = endpoint_secret_crypto.encrypt(raw_secret)

                new_secret = await self.endpoint_secret_repository.create(
                    endpoint_id=endpoint.id,
                    encrypted_secret=encrypted_secret,
                    version=next_version,
                )

            await self.session.commit()
            return EndpointRotateSecretResponse(
                secret=raw_secret,
                version=new_secret.version,
                status=new_secret.status,
                created_at=new_secret.created_at,
            )

        except IntegrityError:
            await self.session.rollback()
            raise EndpointSecretConflictError()

        except Exception:
            await self.session.rollback()
            raise


def validate_safe_webhook_url(url: str) -> None:
    """Validate that a webhook URL has a valid scheme/host and does not point to
    private, loopback, reserved, or link-local addresses (anti-SSRF check).

    Args:
        url: The webhook destination URL to validate.

    Raises:
        EndpointValidationError: If the URL is invalid or targets an internal/unsafe destination.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise EndpointValidationError(
            "Webhook URL must have a valid scheme (http or https) and a valid host."
        )

    if not parsed.hostname:
        raise EndpointValidationError("Webhook URL must have a valid host.")

    if settings.is_production and parsed.scheme != "https":
        raise EndpointValidationError("Webhook URL must use HTTPS in production.")

    hostname = parsed.hostname.lower().strip()
    if is_hostname_local(hostname):
        raise EndpointValidationError(
            "Webhook URL must not point to a private, loopback, reserved, or link-local address."
        )

    # 1. Direct IP address check
    try:
        ip = ipaddress.ip_address(hostname)
        if not is_ip_allowed(ip):
            raise EndpointValidationError(
                "Webhook URL must not point to a private, loopback, reserved, or link-local IP address."
            )
        return
    except ValueError:
        pass

    # 2. Domain name DNS resolution check
    try:
        resolved_ip_str = socket.gethostbyname(hostname)
        resolved_ip = ipaddress.ip_address(resolved_ip_str)
        if not is_ip_allowed(resolved_ip):
            raise EndpointValidationError(
                "Webhook URL must not point to a private, loopback, reserved, or link-local address."
            )
    except socket.gaierror:
        # In production/staging, fail-closed if destination hostname cannot be resolved
        if not settings.is_test:
            raise EndpointValidationError("Webhook destination host could not be resolved.")
    except ValueError:
        raise EndpointValidationError("Webhook destination host resolved to an invalid IP address.")
