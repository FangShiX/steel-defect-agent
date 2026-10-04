from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database.session import get_db
from app.entity.db_models import User
from app.services.notification_service import notification_service

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _serialize(notification):
    return {
        "id": notification.id,
        "kind": notification.kind,
        "title": notification.title,
        "message": notification.message,
        "task_id": notification.task_id,
        "resource_type": notification.resource_type,
        "resource_id": notification.resource_id,
        "request_id": notification.request_id,
        "read_at": notification.read_at,
        "created_at": notification.created_at,
    }


@router.get("")
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items = notification_service.list_for_user(db, current_user.id, unread_only, limit)
    unread = len(notification_service.list_for_user(db, current_user.id, True, 100))
    return {"items": [_serialize(item) for item in items], "unread_count": unread}


@router.post("/read-all")
def mark_all_notifications_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"updated": notification_service.mark_all_read(db, current_user.id)}


@router.post("/{notification_id}/read")
def mark_notification_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _serialize(notification_service.mark_read(db, current_user.id, notification_id))
