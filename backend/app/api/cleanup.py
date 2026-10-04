"""Administrative metadata-only view of retryable resource cleanup work."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database.session import get_db
from app.entity.db_models import User
from app.entity.schemas import PageResponse, ResourceCleanupJobResponse
from app.services.authorization_service import authorization_service
from app.services.resource_lifecycle_service import resource_lifecycle_service

router = APIRouter(prefix="/api/cleanup-jobs", tags=["资源清理"])


@router.get("", response_model=PageResponse)
def list_cleanup_jobs(
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    authorization_service.require_permission(db, current_user, "system:cleanup:read")
    items, total = resource_lifecycle_service.list_cleanup_jobs(
        db, status=status, page=page, page_size=page_size
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "items": [ResourceCleanupJobResponse.model_validate(item) for item in items],
    }


@router.post("/{job_id}/retry", response_model=ResourceCleanupJobResponse)
def retry_cleanup_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    authorization_service.require_permission(db, current_user, "system:cleanup:retry")
    job = resource_lifecycle_service.retry_cleanup_job(db, job_id)
    return ResourceCleanupJobResponse.model_validate(job)
