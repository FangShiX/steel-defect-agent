import asyncio
import os
import warnings
from contextlib import suppress
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Pydantic v2 reserves "model_" prefix; suppress the harmless lint.
warnings.filterwarnings("ignore", message='Field "model_id" has conflict')

from app.api.agent import router as agent_router
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.confirmations import router as confirmations_router
from app.api.detection import router as detection_router
from app.api.health import router as health_router
from app.api.history import router as history_router
from app.api.knowledge import router as knowledge_router
from app.api.notifications import router as notifications_router
from app.api.undo import router as undo_router
from app.api.operation_logs import router as operation_logs_router
from app.api.scenes import router as scenes_router
from app.api.training import router as training_router
from app.api.cleanup import router as cleanup_router
from app.api.files import router as files_router
from app.api.storage import router as storage_router
from app.config.settings import settings
from app.core.exceptions import register_exception_handlers
from app.core.logger import get_logger, setup_logging
from app.core.redis_client import redis_client
from app.database.session import SessionLocal
from app.middleware.request_logger import RequestLogMiddleware
from app.services.detection_service import detection_service
from app.storage.cleanup import cleanup_stale_agent_uploads, retry_pending_cleanups

setup_logging()
logger = get_logger(__name__)


def configure_provider_proxy_bypass() -> None:
    """Bypass a broken system proxy for DashScope only in this backend process."""
    host = urlparse(settings.OPENAI_BASE_URL).hostname
    if host != "dashscope.aliyuncs.com":
        return
    hosts = []
    for name in ("NO_PROXY", "no_proxy"):
        for item in os.environ.get(name, "").split(","):
            item = item.strip()
            if item and item not in hosts:
                hosts.append(item)
    if host not in hosts:
        hosts.append(host)
    value = ",".join(hosts)
    os.environ["NO_PROXY"] = value
    os.environ["no_proxy"] = value


def init_minio() -> None:
    try:
        from app.storage.minio_client import MinIOClient

        minio_client = MinIOClient()
        logger.info("MinIO bucket '%s' initialized", minio_client.bucket_name)
    except Exception as exc:
        logger.warning("MinIO initialization failed: %s", exc)


def retry_resource_cleanups() -> dict:
    lock_key = "ssdd:resource-cleanup-lock"
    lock_token = uuid4().hex
    if not redis_client.acquire_lock(lock_key, lock_token, settings.CLEANUP_LOCK_TTL_SECONDS):
        logger.debug("Pending resource cleanup skipped because another worker holds the lock")
        return {"attempted": 0, "succeeded": 0, "skipped": True}
    db = SessionLocal()
    try:
        result = retry_pending_cleanups(db)
        if hasattr(db, "query"):
            removed_uploads = cleanup_stale_agent_uploads(db)
            if removed_uploads:
                logger.info("Stale chat attachments removed: %s", removed_uploads)
        if result["attempted"]:
            logger.info("Pending resource cleanup retried: %s", result)
        return result
    finally:
        db.close()
        redis_client.release_lock(lock_key, lock_token)


async def _cleanup_loop() -> None:
    """Retry durable deletions while the API process is running."""
    while True:
        try:
            await asyncio.to_thread(retry_resource_cleanups)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Pending resource cleanup retry failed")
        await asyncio.sleep(settings.CLEANUP_RETRY_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("Starting service")
    configure_provider_proxy_bypass()
    cleanup_task = None
    if not settings.SKIP_EXTERNAL_STARTUP:
        init_minio()
        asyncio.create_task(asyncio.to_thread(detection_service.warmup_models))
        cleanup_task = asyncio.create_task(_cleanup_loop())
    try:
        yield
    finally:
        if cleanup_task:
            cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await cleanup_task
        logger.info("Service stopped")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="YOLOv11 object detection agent platform API",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLogMiddleware)
register_exception_handlers(app)

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(confirmations_router)
app.include_router(detection_router)
app.include_router(agent_router)
app.include_router(health_router)
app.include_router(history_router)
app.include_router(operation_logs_router)
app.include_router(scenes_router)
app.include_router(training_router)
app.include_router(knowledge_router)
app.include_router(notifications_router)
app.include_router(undo_router)
app.include_router(cleanup_router)
app.include_router(files_router)
app.include_router(storage_router)


@app.get("/")
def root():
    return {"message": f"Welcome to {settings.APP_NAME}", "version": settings.APP_VERSION, "docs": "/docs", "redoc": "/redoc"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=[str(Path(__file__).parent / "app")],
        reload_excludes=["**/__pycache__/**", "**/*.pyc"],
        reload_delay=0.5,
        access_log=False,
        ws_ping_interval=20,
        ws_ping_timeout=20,
    )
