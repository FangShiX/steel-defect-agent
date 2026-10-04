from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.exc import OperationalError

from app.core.logger import get_logger
from app.core.privacy import redact_value


logger = get_logger(__name__)
_SENSITIVE_FIELD_TOKENS = ("password", "token", "secret", "api_key", "authorization")
_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


def resource_detail(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def _retryable(status_code: int) -> bool:
    return status_code in _RETRYABLE_STATUS_CODES


def _error_context(request: Request) -> dict:
    return {
        "path": request.url.path,
        "request_id": getattr(request.state, "request_id", None),
        "task_id": getattr(request.state, "task_id", None),
        "session_id": getattr(request.state, "session_id", None),
        "user_id": getattr(request.state, "user_id", None),
    }


def _safe_validation_errors(errors: list[dict]) -> list[dict]:
    """Keep validation diagnostics useful without returning submitted secrets."""
    safe_errors = []
    for error in errors:
        safe_error = dict(error)
        location = safe_error.get("loc", ())
        if any(
            isinstance(part, str) and any(token in part.lower() for token in _SENSITIVE_FIELD_TOKENS)
            for part in location
        ):
            safe_error["input"] = "[redacted]"
        safe_errors.append(safe_error)
    return safe_errors


def _record_request_error(request: Request, status_code: int, error_code: str, detail) -> None:
    """Persist a redacted request failure without masking the original response."""
    # Confirmation challenges are an intentional two-step safety flow. They
    # are handled by the frontend and should not pollute the failure summary.
    if status_code == 428 and error_code == "CONFIRMATION_REQUIRED":
        return
    # The client-error endpoint is best-effort telemetry. A malformed or
    # unauthenticated telemetry submission must not become another audit error.
    if request.url.path.endswith("/operation-logs/client-error"):
        return
    try:
        from app.database.session import SessionLocal
        from app.entity.db_models import User
        from app.services.operation_log_service import operation_log_service

        db = SessionLocal()
        try:
            user_id = getattr(request.state, "user_id", None)
            user = db.query(User).filter(User.id == user_id).first() if user_id else None
            operation_log_service.record(
                db, user=user, module="system", action="request_error",
                target_type="http_request", target_id=request.url.path,
                description=f"HTTP {status_code} {error_code}", status="failure",
                error_message=str(detail), request=request,
                task_id=getattr(request.state, "task_id", None),
                session_id=getattr(request.state, "session_id", None),
            )
        finally:
            db.close()
    except Exception:
        logger.exception("Failed to persist request error audit")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        errors = _safe_validation_errors(exc.errors())
        _record_request_error(request, 422, "VALIDATION_ERROR", errors)
        logger.warning("Validation error: %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=422,
            content={
                "code": 422,
                "status_code": 422,
                "error_code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "detail": errors,
                **_error_context(request),
                "retryable": False,
            },
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        logger.warning("HTTP error: %s %s status=%s detail=%s", request.method, request.url.path, exc.status_code, redact_value(exc.detail))
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": f"HTTP_{exc.status_code}", "message": exc.detail}
        _record_request_error(request, exc.status_code, detail.get("code", f"HTTP_{exc.status_code}"), detail.get("message"))
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.status_code,
                "status_code": exc.status_code,
                "error_code": detail.get("code"),
                "message": detail.get("message"),
                "detail": detail,
                **_error_context(request),
                "retryable": _retryable(exc.status_code),
            },
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(StarletteHTTPException)
    async def starlette_exception_handler(request: Request, exc: StarletteHTTPException):
        logger.warning("HTTP error: %s %s status=%s detail=%s", request.method, request.url.path, exc.status_code, redact_value(exc.detail))
        _record_request_error(request, exc.status_code, f"HTTP_{exc.status_code}", exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.status_code,
                "status_code": exc.status_code,
                "error_code": f"HTTP_{exc.status_code}",
                "message": exc.detail,
                "detail": {"code": f"HTTP_{exc.status_code}", "message": exc.detail},
                **_error_context(request),
                "retryable": _retryable(exc.status_code),
            },
        )

    @app.exception_handler(OperationalError)
    async def database_exception_handler(request: Request, _exc: OperationalError):
        """Expose transient database outages as a safe, retryable service error."""
        logger.exception("Database unavailable: %s %s", request.method, request.url.path)
        _record_request_error(request, 503, "DATABASE_UNAVAILABLE", "Database service unavailable")
        return JSONResponse(
            status_code=503,
            content={
                "code": 503,
                "status_code": 503,
                "error_code": "DATABASE_UNAVAILABLE",
                "message": "Database service unavailable",
                "detail": {"code": "DATABASE_UNAVAILABLE", "message": "Database service unavailable"},
                **_error_context(request),
                "retryable": True,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error: %s %s", request.method, request.url.path)
        _record_request_error(request, 500, "INTERNAL_ERROR", "Internal server error")
        return JSONResponse(
            status_code=500,
            content={
                "code": 500,
                "status_code": 500,
                "error_code": "INTERNAL_ERROR",
                "message": "Internal server error",
                "detail": {"code": "INTERNAL_ERROR", "message": "Internal server error"},
                **_error_context(request),
                "retryable": True,
            },
        )
