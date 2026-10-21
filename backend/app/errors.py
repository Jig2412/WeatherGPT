"""Domain errors and the FastAPI exception handlers that render them."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base class for expected, user-visible failures."""

    status_code = 400
    code = "error"

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        code: str | None = None,
        status_code: int | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.retry_after = retry_after


class UpstreamError(AppError):
    """A third-party provider failed or returned something unusable."""

    status_code = 502
    code = "upstream_error"

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        status_code: int = 502,
        code: str = "upstream_error",
        retry_after: int | None = None,
    ) -> None:
        super().__init__(
            message,
            provider=provider,
            code=code,
            status_code=status_code,
            retry_after=retry_after,
        )


class RateLimitError(AppError):
    status_code = 429
    code = "rate_limited"

    def __init__(self, message: str, *, provider: str | None = None, retry_after: int = 60) -> None:
        super().__init__(message, provider=provider, retry_after=retry_after)


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"


class MissingConfigError(AppError):
    """Raised when a feature needs a credential that has not been configured."""

    status_code = 503
    code = "missing_configuration"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        headers = {}
        if exc.retry_after:
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(
            status_code=exc.status_code,
            headers=headers,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "provider": exc.provider,
                    "retry_after": exc.retry_after,
                }
            },
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "Unexpected server error.",
                    "provider": None,
                    "retry_after": None,
                }
            },
        )
