"""Durable, single-use confirmation tickets for high-risk operations."""

import hashlib
import json
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.entity.db_models import ActionConfirmation


class ActionConfirmationService:
    TTL_MINUTES = 10

    @staticmethod
    def _hash_payload(payload: dict) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @classmethod
    def prepare(
        cls, db: Session, *, user_id: int, operation: str, target_type: str,
        target_id: str | None, impact: dict, payload: dict,
        request_id: str | None = None, task_id: str | None = None, session_id: str | None = None,
    ) -> ActionConfirmation:
        item = ActionConfirmation(
            confirmation_uuid=str(uuid4()), user_id=user_id, operation=operation,
            target_type=target_type, target_id=target_id, impact=impact,
            payload_hash=cls._hash_payload(payload), status="pending",
            expires_at=datetime.now() + timedelta(minutes=cls.TTL_MINUTES),
            request_id=request_id, task_id=task_id, session_id=session_id,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    @staticmethod
    def confirm(db: Session, confirmation_uuid: str, user_id: int) -> ActionConfirmation:
        item = db.query(ActionConfirmation).filter(
            ActionConfirmation.confirmation_uuid == confirmation_uuid,
            ActionConfirmation.user_id == user_id,
        ).first()
        if not item:
            raise HTTPException(status_code=404, detail={"code": "CONFIRMATION_NOT_FOUND", "message": "确认请求不存在"})
        if item.expires_at <= datetime.now():
            item.status = "expired"
            db.commit()
            raise HTTPException(status_code=409, detail={"code": "CONFIRMATION_EXPIRED", "message": "确认请求已过期"})
        if item.status == "consumed":
            raise HTTPException(status_code=409, detail={"code": "CONFIRMATION_CONSUMED", "message": "危险操作已经执行，不可重复执行"})
        item.status = "confirmed"
        item.confirmed_at = datetime.now()
        db.commit()
        db.refresh(item)
        return item

    @staticmethod
    def consume(
        db: Session, confirmation_uuid: str, *, user_id: int, operation: str,
        target_type: str, target_id: str | None, payload: dict,
    ) -> ActionConfirmation:
        item = db.query(ActionConfirmation).filter(
            ActionConfirmation.confirmation_uuid == confirmation_uuid,
            ActionConfirmation.user_id == user_id,
        ).with_for_update().first()
        if not item:
            raise HTTPException(status_code=404, detail={"code": "CONFIRMATION_NOT_FOUND", "message": "确认请求不存在"})
        if item.status != "confirmed":
            raise HTTPException(status_code=428, detail={"code": "CONFIRMATION_REQUIRED", "message": "危险操作尚未确认"})
        if item.expires_at <= datetime.now():
            item.status = "expired"
            db.commit()
            raise HTTPException(status_code=409, detail={"code": "CONFIRMATION_EXPIRED", "message": "确认请求已过期"})
        if (item.operation, item.target_type, item.target_id, item.payload_hash) != (
            operation, target_type, target_id, ActionConfirmationService._hash_payload(payload)
        ):
            raise HTTPException(status_code=409, detail={"code": "CONFIRMATION_MISMATCH", "message": "确认对象或影响范围已发生变化，请重新确认"})
        item.status = "consumed"
        item.consumed_at = datetime.now()
        db.commit()
        db.refresh(item)
        return item

    @classmethod
    def require_or_prepare(
        cls, db: Session, *, confirmation_uuid: str | None, user_id: int,
        operation: str, target_type: str, target_id: str | None, impact: dict,
        payload: dict, request_id: str | None = None,
    ) -> ActionConfirmation:
        if not confirmation_uuid:
            # Most protected endpoints already identify the resource through
            # target_id. Preserve that correlation in the durable confirmation
            # record without requiring every endpoint to duplicate the mapping.
            task_id = target_id if "task" in target_type.lower() else None
            session_id = target_id if "session" in target_type.lower() else None
            item = cls.prepare(
                db, user_id=user_id, operation=operation, target_type=target_type,
                target_id=target_id, impact=impact, payload=payload, request_id=request_id,
                task_id=task_id, session_id=session_id,
            )
            raise HTTPException(status_code=428, detail={
                "code": "CONFIRMATION_REQUIRED", "message": "请确认高风险操作",
                "confirmation_id": item.confirmation_uuid, "operation": operation,
                "target_type": target_type, "target_id": target_id, "impact": impact,
                "expires_at": item.expires_at.isoformat(),
            })
        return cls.consume(
            db, confirmation_uuid, user_id=user_id, operation=operation,
            target_type=target_type, target_id=target_id, payload=payload,
        )


action_confirmation_service = ActionConfirmationService()
