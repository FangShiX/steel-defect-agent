from datetime import datetime

from sqlalchemy.orm import Session

from app.entity.db_models import Notification


class NotificationService:
    @staticmethod
    def safe_create(db: Session, *args, **kwargs) -> None:
        try:
            NotificationService.create(db, *args, **kwargs)
        except Exception:
            db.rollback()

    @staticmethod
    def create(
        db: Session,
        user_id: int,
        kind: str,
        title: str,
        message: str,
        *,
        task_id: str | int | None = None,
        resource_type: str | None = None,
        resource_id: str | int | None = None,
        request_id: str | None = None,
    ) -> Notification:
        notification = Notification(
            user_id=user_id, kind=kind, title=title, message=message,
            task_id=str(task_id) if task_id is not None else None,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            request_id=request_id,
        )
        db.add(notification)
        db.commit()
        db.refresh(notification)
        return notification

    @staticmethod
    def list_for_user(db: Session, user_id: int, unread_only: bool = False, limit: int = 50):
        query = db.query(Notification).filter(Notification.user_id == user_id)
        if unread_only:
            query = query.filter(Notification.read_at.is_(None))
        return query.order_by(Notification.created_at.desc()).limit(limit).all()

    @staticmethod
    def mark_read(db: Session, user_id: int, notification_id: int) -> Notification:
        notification = db.query(Notification).filter(
            Notification.id == notification_id, Notification.user_id == user_id,
        ).first()
        if notification is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail={"code": "NOTIFICATION_NOT_FOUND", "message": "notification not found"})
        notification.read_at = notification.read_at or datetime.now()
        db.commit()
        db.refresh(notification)
        return notification

    @staticmethod
    def mark_all_read(db: Session, user_id: int) -> int:
        updated = db.query(Notification).filter(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
        ).update({Notification.read_at: datetime.now()}, synchronize_session=False)
        db.commit()
        return updated


notification_service = NotificationService()
