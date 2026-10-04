from datetime import datetime

from fastapi import APIRouter
from sqlalchemy import text

from app.config.settings import settings
from app.database.session import SessionLocal
from app.storage.minio_client import MinIOClient


router = APIRouter(prefix="/api/health", tags=["health"])


def check_database() -> dict:
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        return {"status": "healthy", "message": "PostgreSQL connection ok"}
    except Exception:
        return {"status": "unhealthy", "message": "PostgreSQL connection failed"}
    finally:
        if "db" in locals():
            db.close()


def check_redis() -> dict:
    try:
        import redis

        client = redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        client.ping()
        return {"status": "healthy", "message": "Redis connection ok"}
    except Exception:
        return {"status": "unhealthy", "message": "Redis connection failed"}


def check_minio() -> dict:
    try:
        client = MinIOClient()
        exists = client.client.bucket_exists(client.bucket_name)
        return {
            "status": "healthy" if exists else "unhealthy",
            "message": f"Bucket {client.bucket_name} {'exists' if exists else 'does not exist'}",
        }
    except Exception:
        return {"status": "unhealthy", "message": "Object storage connection failed"}


@router.get("")
def health_check():
    return {
        "code": 200,
        "message": "ok",
        "data": {
            "status": "healthy",
            "app_name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "timestamp": datetime.utcnow().isoformat(),
        },
    }


@router.get("/detail")
def health_detail():
    services = {
        "database": check_database(),
        "redis": check_redis(),
        "minio": check_minio(),
    }
    overall = "healthy" if all(item["status"] == "healthy" for item in services.values()) else "degraded"
    return {
        "code": 200,
        "message": "ok",
        "data": {
            "status": overall,
            "app_name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "services": services,
            "timestamp": datetime.utcnow().isoformat(),
        },
    }
