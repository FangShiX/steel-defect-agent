"""Short-lived object downloads through the app's public gateway."""
from urllib.parse import quote

import jwt
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.config.settings import settings
from app.storage.minio_client import MinIOClient

router = APIRouter(prefix="/api/storage", tags=["Storage downloads"])


@router.get("/{bucket}/{object_name:path}")
def download_object(bucket: str, object_name: str, token: str):
    try:
        claims = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM],
                            audience="storage", options={"require": ["exp", "bucket", "object"]})
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=403, detail="Download link is invalid or expired") from exc
    if bucket != settings.MINIO_BUCKET or claims["bucket"] != bucket or claims["object"] != object_name:
        raise HTTPException(status_code=403, detail="Download link does not grant access to this object")
    try:
        storage = MinIOClient()
        response = storage.client.get_object(bucket, object_name)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Object is unavailable") from exc

    def stream():
        try:
            yield from response.stream(64 * 1024)
        finally:
            response.close()
            response.release_conn()

    content_type = response.headers.get("Content-Type", "application/octet-stream")
    if not content_type.startswith(("image/", "video/")) or content_type == "image/svg+xml":
        content_type = "application/octet-stream"
    return StreamingResponse(stream(), media_type=content_type, headers={
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(object_name.rsplit("/", 1)[-1], safe=""),
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Cache-Control": "private, no-store",
    })
