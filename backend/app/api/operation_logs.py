"""
操作审计日志 API（管理员）
- GET /api/operation-logs 分页查询操作日志，支持按用户/模块/动作/状态筛选

写日志的动作分散在各个业务路由里（登录、密码修改、用户删除、模型默认切换等），
本模块只提供读取入口，给管理端的审计页面用。
"""
from typing import Optional
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from sqlalchemy import func

from app.api.auth import get_current_user
from app.database.session import get_db
from app.entity.db_models import OperationLog, User
from app.entity.schemas import OperationLogResponse, PageResponse
from app.core.privacy import redact_text
from app.services.operation_log_service import operation_log_service
from app.services.authorization_service import authorization_service

router = APIRouter(prefix="/api/operation-logs", tags=["操作审计"])


def _safe_log_response(item) -> dict:
    data = OperationLogResponse.model_validate(item).model_dump()
    data["description"] = redact_text(data.get("description"))
    data["error_message"] = redact_text(data.get("error_message"))
    return data


class ClientErrorPayload(BaseModel):
    type: str = Field(default="frontend_error", max_length=50)
    message: str = Field(default="client error", max_length=500)
    request_id: Optional[str] = Field(default=None, max_length=100)
    task_id: Optional[str] = Field(default=None, max_length=100)
    session_id: Optional[str] = Field(default=None, max_length=100)
    user_id: Optional[str] = Field(default=None, max_length=100)
    pathname: Optional[str] = Field(default=None, max_length=300)


@router.post("/client-error", status_code=202)
def record_client_error(
    payload: ClientErrorPayload,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    operation_log_service.record(
        db, user=current_user, module="frontend", action="client_error",
        target_type="client", target_id=payload.type, status="failure",
        description=f"{payload.type}: {payload.message}", request=request,
        request_id=payload.request_id, task_id=payload.task_id,
        session_id=payload.session_id,
    )
    return {"accepted": True}


@router.get("/summary")
def error_summary(
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="admin permission required")
    rows = db.query(
        OperationLog.module, OperationLog.action, OperationLog.status,
        func.count(OperationLog.id).label("count"),
        func.max(OperationLog.created_at).label("last_seen"),
    ).filter(OperationLog.status == "failure").group_by(
        OperationLog.module, OperationLog.action, OperationLog.status,
    ).order_by(func.count(OperationLog.id).desc()).limit(limit).all()
    return {"items": [
        {"module": row.module, "action": row.action, "status": row.status,
         "count": row.count, "last_seen": row.last_seen}
        for row in rows
    ]}


@router.get("", response_model=PageResponse)
def list_operation_logs(
    user_id: Optional[int] = Query(default=None, description="按操作用户过滤"),
    module: Optional[str] = Query(default=None, description="按模块过滤"),
    action: Optional[str] = Query(default=None, description="按动作类型过滤"),
    status: Optional[str] = Query(default=None, description="success/failure"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """分页查询操作日志，仅管理员可访问"""
    authorization_service.require_permission(db, current_user, "system:audit:read")

    items, total = operation_log_service.list_logs(
        db, user_id=user_id, module=module, action=action, status=status,
        page=page, page_size=page_size,
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if page_size else 0,
        "items": [_safe_log_response(item) for item in items],
    }


# Canonical admin export consumed by AdminPage.
@router.get("/export")
def export_operation_logs(
    request: Request,
    user_id: Optional[int] = Query(default=None),
    module: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export a bounded, already-redacted audit CSV for administrators."""
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="admin permission required")
    items, _ = operation_log_service.list_logs(
        db, user_id=user_id, module=module, action=action, status=status,
        page=1, page_size=5000,
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["created_at", "user_id", "username", "module", "action", "target_type", "target_id", "request_id", "task_id", "session_id", "status", "description", "error_message"])
    for item in items:
        writer.writerow([
            item.created_at, item.user_id, item.username, item.module, item.action,
            item.target_type, item.target_id, item.request_id, item.task_id,
            item.session_id, item.status, redact_text(item.description), redact_text(item.error_message),
        ])
    operation_log_service.record(
        db, user=current_user, module="system", action="export_audit_logs",
        description="export redacted audit logs", request=request,
    )
    return PlainTextResponse(
        output.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="audit_logs.csv"'},
    )
