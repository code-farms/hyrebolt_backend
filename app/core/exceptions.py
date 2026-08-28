from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.logging import get_logger

logger = get_logger(__name__)


class AppException(Exception):
    """Base class for application-raised errors that map to a specific HTTP response."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: str = "internal_error"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class DependencyUnavailableError(AppException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "dependency_unavailable"


class UnauthorizedError(AppException):
    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "invalid_token"

    def __init__(self, message: str, error_code: str | None = None) -> None:
        if error_code is not None:
            self.error_code = error_code
        super().__init__(message)


class ConflictError(AppException):
    status_code = status.HTTP_409_CONFLICT
    error_code = "conflict"

    def __init__(self, message: str, error_code: str = "conflict") -> None:
        self.error_code = error_code
        super().__init__(message)


class RateLimitedError(AppException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "rate_limited"


class NotFoundError(AppException):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = "not_found"


class InvalidInputError(AppException):
    status_code = 422
    error_code = "invalid_input"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppException)
    async def handle_app_exception(request: Request, exc: AppException) -> JSONResponse:
        logger.warning(
            "app_exception",
            path=request.url.path,
            error_code=exc.error_code,
            message=exc.message,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"error_code": exc.error_code, "message": exc.message},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Custom validators surface the raised exception under ctx.error;
        # encode it as text so the response stays JSON-serializable. The
        # submitted value (`input`) is dropped: it may be a password or a
        # large payload and the client already has it.
        errors = jsonable_encoder(
            [{k: v for k, v in error.items() if k not in ("input", "url")} for error in exc.errors()],
            custom_encoder={Exception: str},
        )
        logger.warning("validation_error", path=request.url.path, errors=errors)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"error_code": "validation_error", "message": errors},
        )

    @app.exception_handler(Exception)
    async def handle_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_exception", path=request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error_code": "internal_error", "message": "An unexpected error occurred."},
        )
