from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base error with a user-facing message and a stable machine code."""

    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code


class NotConnected(AppError):
    status_code = 503
    code = "provider_not_connected"


class TokenInvalid(AppError):
    status_code = 503
    code = "provider_token_invalid"


class RateLimited(AppError):
    status_code = 503
    code = "provider_rate_limited"


class ProviderUnavailable(AppError):
    status_code = 502
    code = "provider_unavailable"


class ProviderRequestError(AppError):
    status_code = 400
    code = "provider_rejected_request"


class NotFound(AppError):
    status_code = 404
    code = "not_found"


async def app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )
