from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.entity.db_models import UndoAction


class UndoService:
    @staticmethod
    def create(db: Session, user_id: int, operation: str, payload: dict, ttl_seconds: int = 30) -> UndoAction:
        action = UndoAction(
            undo_uuid=str(uuid4()), user_id=user_id, operation=operation,
            payload=payload, expires_at=datetime.now() + timedelta(seconds=ttl_seconds),
        )
        db.add(action)
        db.commit()
        db.refresh(action)
        return action

    @staticmethod
    def consume(db: Session, user_id: int, undo_uuid: str) -> UndoAction:
        action = db.query(UndoAction).filter(
            UndoAction.undo_uuid == undo_uuid, UndoAction.user_id == user_id,
        ).with_for_update().first()
        if action is None or action.consumed_at or action.expires_at <= datetime.now():
            raise HTTPException(status_code=409, detail={"code": "UNDO_EXPIRED", "message": "undo action is expired or already used"})
        action.consumed_at = datetime.now()
        db.commit()
        db.refresh(action)
        return action


undo_service = UndoService()
