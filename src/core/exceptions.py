import logging
import traceback
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

logger = logging.getLogger("api.exceptions")


class AppException(Exception):
    def __init__(self, status_code: int, detail: str, error_code: str | None = None):
        self.status_code = status_code
        self.detail = detail
        self.error_code = error_code


def extract_error_location(exc: Exception) -> str:
    """Helper function to get the file and line number from an exception."""
    tb = traceback.extract_tb(exc.__traceback__)
    if tb:
        last_frame = tb[-1]
        return f"{last_frame.filename}:{last_frame.lineno}"
    return "unknown location"


def register_exception_handlers(app: FastAPI):

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "message": exc.detail,
                    "code": exc.error_code,
                    "status": exc.status_code,
                }
            },
        )

    @app.exception_handler(ValidationError)
    async def validation_exception_handler(request: Request, exc: ValidationError):
        req_id = getattr(request.state, "request_id", "unknown")
        error_location = extract_error_location(exc)

        # Extract exactly which fields failed and why
        failed_fields = []
        for err in exc.errors():
            field_path = ".".join(str(x) for x in err["loc"])
            failed_fields.append(f"{field_path} ({err['msg']})")

        fields_str = ", ".join(failed_fields)

        logger.error(
            f"req_id={req_id} Validation Error at {error_location} | "
            f"Problematic fields: {fields_str}",
            exc_info=exc,
        )

        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "message": "Validation failed",
                    "code": "VALIDATION_ERROR",
                    "details": exc.errors(),
                }
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        req_id = getattr(request.state, "request_id", "unknown")
        error_location = extract_error_location(exc)

        logger.exception(
            f"req_id={req_id} Unhandled crash at {error_location} | Error: {str(exc)}"
        )

        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "message": "Internal server error",
                    "code": "INTERNAL_ERROR",
                }
            },
        )
