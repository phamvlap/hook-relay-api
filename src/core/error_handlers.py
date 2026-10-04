import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.core.client_ip import get_client_ip
from src.core.exceptions import (
    AppError,
    ConflictError,
    NotFoundError,
    RateLimitExceededError,
    UnauthorizedError,
    ValidationError,
)

logger = logging.getLogger(__name__)


def _error_response(
    status_code: int,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"message": message, "details": details or {}}},
        headers=headers,
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFoundError)
    async def not_found_exception_handler(request: Request, exc: NotFoundError):
        return _error_response(status.HTTP_404_NOT_FOUND, exc.message)

    @app.exception_handler(ConflictError)
    async def conflict_exception_handler(request: Request, exc: ConflictError):
        return _error_response(status.HTTP_409_CONFLICT, exc.message)

    @app.exception_handler(ValidationError)
    async def validation_exception_handler(request: Request, exc: ValidationError):
        return _error_response(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message)

    @app.exception_handler(AppError)
    async def app_error_exception_handler(request: Request, exc: AppError):
        return _error_response(status.HTTP_400_BAD_REQUEST, exc.message)

    @app.exception_handler(UnauthorizedError)
    async def unauthorized_exception_handler(request: Request, exc: UnauthorizedError):
        return _error_response(status.HTTP_401_UNAUTHORIZED, exc.message)

    @app.exception_handler(RateLimitExceededError)
    async def rate_limit_exception_handler(request: Request, exc: RateLimitExceededError):
        headers = {
            "Retry-After": str(max(1, int(exc.retry_after) + 1)),
            "X-RateLimit-Limit": str(exc.limit),
            "X-RateLimit-Remaining": str(exc.remaining),
            "X-RateLimit-Reset": str(exc.reset),
        }
        return _error_response(
            status.HTTP_429_TOO_MANY_REQUESTS,
            exc.message,
            details={
                "retry_after": round(exc.retry_after, 2),
                "limit": exc.limit,
                "remaining": exc.remaining,
                "reset": exc.reset,
            },
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
        return _error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Request validation error",
            details={"errors": exc.errors()},
        )

    @app.exception_handler(StarletteHTTPException)
    async def starlette_http_exception_handler(request: Request, exc: StarletteHTTPException):
        return _error_response(
            exc.status_code,
            exc.detail if isinstance(exc.detail, str) else "HTTP error",
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        try:
            method = getattr(request, "method", "UNKNOWN")
            url = getattr(request, "url", None)
            path = getattr(url, "path", "UNKNOWN")

            try:
                client_ip = get_client_ip(request)
            except (AttributeError, TypeError, ValueError):
                client = getattr(request, "client", None)
                client_ip = getattr(client, "host", "unknown") or "unknown"

            state = getattr(request, "state", None)
            auth = getattr(state, "auth", None)
            owner_id = str(getattr(auth, "owner_id", None)) if auth else None

            extra: dict[str, Any] = {
                "http_method": method,
                "http_path": path,
                "client_ip": client_ip,
                "error_type": type(exc).__name__,
            }
            if owner_id:
                extra["owner_id"] = owner_id

            logger.exception(
                "Unhandled exception occurred while processing %s %s: %s",
                method,
                path,
                exc or type(exc).__name__,
                extra=extra,
            )
        except Exception:
            # Fallback to guarantee exception logging even if request inspection fails
            logger.exception("Unhandled exception occurred: %s", exc)

        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "An unexpected error occurred.",
        )
