import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.logger import get_logger


logger = get_logger(__name__)


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.perf_counter()
        request_id = request.headers.get("X-Request-ID") or uuid4().hex
        request.state.request_id = request_id
        response = None
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            status_code = response.status_code if response is not None else 500
            # Monitoring polls are expected high-frequency traffic. Keep
            # their diagnostics available at DEBUG without flooding normal
            # backend logs every few seconds.
            log = logger.debug if request.url.path.startswith("/api/training/status/") or request.url.path.startswith("/api/training/metrics/") else logger.info
            log(
                "request_id=%s %s %s status=%s duration=%.2fms client=%s",
                request_id,
                request.method,
                request.url.path,
                status_code,
                elapsed_ms,
                request.client.host if request.client else "-",
            )
