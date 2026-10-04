"""Prepare and confirm high-risk actions before their execution endpoint runs."""

from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database.session import get_db
from app.services.action_confirmation_service import action_confirmation_service

router = APIRouter(prefix="/api/confirmations", tags=["高风险操作确认"])


class ConfirmationCreate(BaseModel):
    operation: str = Field(..., min_length=1, max_length=80)
    target_type: str = Field(..., min_length=1, max_length=80)
    target_id: Optional[str] = Field(None, max_length=120)
    impact: dict = Field(default_factory=dict)
    payload: dict = Field(default_factory=dict)
    task_id: Optional[str] = None
    session_id: Optional[str] = None


def _response(item):
    return {
        "id": item.confirmation_uuid,
        "operation": item.operation,
        "target_type": item.target_type,
        "target_id": item.target_id,
        "impact": item.impact,
        "status": item.status,
        "created_at": item.created_at,
        "expires_at": item.expires_at,
        "confirmed_at": item.confirmed_at,
        "consumed_at": item.consumed_at,
        "task_id": item.task_id,
        "session_id": item.session_id,
    }


@router.post("", status_code=201)
def prepare_confirmation(
    payload: ConfirmationCreate,
    request: Request,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = action_confirmation_service.prepare(
        db, user_id=current_user.id, operation=payload.operation,
        target_type=payload.target_type, target_id=payload.target_id,
        impact=payload.impact, payload=payload.payload,
        request_id=getattr(request.state, "request_id", None),
        task_id=payload.task_id, session_id=payload.session_id,
    )
    return _response(item)


@router.post("/{confirmation_id}/confirm")
def confirm_action(
    confirmation_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _response(action_confirmation_service.confirm(db, confirmation_id, current_user.id))
