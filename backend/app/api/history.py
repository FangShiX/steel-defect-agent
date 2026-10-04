"""
检测记录与统计 API 路由
- GET    /api/history                    检测任务分页历史（支持筛选）
- GET    /api/history/statistics/summary 检测统计
- GET    /api/history/{task_id}          检测任务详情（含结果列表）
- DELETE /api/history/{task_id}          删除检测任务
"""
from datetime import date
import csv
import io
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.config.settings import settings
from app.database.session import get_db
from app.entity.db_models import DetectionTask, User
from app.entity.schemas import (
    DetectionTaskResponse, DetectionTaskDetail, DetectionResultResponse,
    DetectionStatistics, PageResponse,
)
from app.services.history_service import history_service
from app.services.operation_log_service import operation_log_service
from app.services.action_confirmation_service import action_confirmation_service
from app.services.undo_service import undo_service
from app.storage.minio_client import MinIOClient
from app.services.authorization_service import authorization_service

router = APIRouter(prefix="/api/history", tags=["检测历史"])


def _task_to_response(task) -> DetectionTaskResponse:
    data = DetectionTaskResponse.model_validate(task)
    data.scene_name = task.scene.display_name if task.scene else None
    return data


def _legacy_object_key(value: str | None) -> str | None:
    """Extract an object key from a legacy persisted MinIO URL, if possible."""
    if not value:
        return None
    from app.storage.minio_client import object_key_from_url
    return object_key_from_url(value)


def _result_to_response(result, minio: MinIOClient) -> DetectionResultResponse:
    data = DetectionResultResponse.model_validate(result)
    original_key = result.original_object_key or _legacy_object_key(result.image_path)
    annotated_key = result.annotated_object_key or _legacy_object_key(result.annotated_image_url)
    # Permission has already been checked on the owning task before this helper
    # is called. Generate a fresh short-lived URL for every response.
    data.image_path = minio.get_presigned_url(original_key) if original_key else ""
    data.annotated_image_url = minio.get_presigned_url(annotated_key) if annotated_key else None
    return data


@router.get("", response_model=PageResponse)
def list_history(
    scene_id: int | None = None,
    task_type: str | None = None,
    status: str | None = None,
    media_type: str | None = Query(default=None, pattern="^(image|video|frame)$"),
    keyword: str | None = Query(default=None, max_length=100),
    owner_user_id: int | None = Query(default=None, ge=1),
    start_date: date | None = None,
    end_date: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """分页查询检测历史；管理员可查看所有用户的记录，普通用户只能查看自己的"""
    can_read_all = authorization_service.has_permission(db, current_user, "detection:task:read_all")
    items, total = history_service.list_tasks(
        db, user_id=current_user.id, is_superuser=can_read_all,
        scene_id=scene_id, task_type=task_type, status=status,
        start_date=start_date, end_date=end_date,
        page=page, page_size=page_size, media_type=media_type,
        keyword=keyword,
        owner_user_id=owner_user_id if current_user.is_superuser else None,
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if page_size else 0,
        "items": [_task_to_response(i) for i in items],
    }


@router.get("/statistics/summary", response_model=DetectionStatistics)
def get_statistics(
    days: int = Query(default=30, ge=1, le=365),
    scene_id: int | None = None,
    task_type: str | None = None,
    status: str | None = None,
    media_type: str | None = Query(default=None, pattern="^(image|video|frame)$"),
    keyword: str | None = Query(default=None, max_length=100),
    owner_user_id: int | None = Query(default=None, ge=1),
    start_date: date | None = None,
    end_date: date | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """检测统计数据：总量、平均耗时、类别分布、每日趋势、场景分布"""
    return history_service.get_statistics(
        db, user_id=current_user.id, is_superuser=current_user.is_superuser,
        days=days, scene_id=scene_id, task_type=task_type, status=status,
        start_date=start_date, end_date=end_date, media_type=media_type,
        keyword=keyword,
        owner_user_id=owner_user_id if current_user.is_superuser else None,
    )


@router.get("/export", response_class=PlainTextResponse)
def export_history_before_detail(
    scene_id: int | None = None,
    task_type: str | None = None,
    status: str | None = None,
    media_type: str | None = Query(default=None, pattern="^(image|video|frame)$"),
    keyword: str | None = Query(default=None, max_length=100),
    owner_user_id: int | None = Query(default=None, ge=1),
    start_date: date | None = None,
    end_date: date | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return export_history(
        scene_id, task_type, status, start_date, end_date, current_user, db,
        media_type=media_type, keyword=keyword,
        owner_user_id=owner_user_id if current_user.is_superuser else None,
    )


@router.get("/statistics/export", response_class=PlainTextResponse)
def export_statistics(
    days: int = Query(default=30, ge=1, le=365),
    scene_id: int | None = None,
    task_type: str | None = None,
    status: str | None = None,
    media_type: str | None = Query(default=None, pattern="^(image|video|frame)$"),
    keyword: str | None = Query(default=None, max_length=100),
    owner_user_id: int | None = Query(default=None, ge=1),
    start_date: date | None = None,
    end_date: date | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stats = history_service.get_statistics(
        db, user_id=current_user.id, is_superuser=current_user.is_superuser,
        days=days, scene_id=scene_id, task_type=task_type, status=status,
        media_type=media_type, keyword=keyword, start_date=start_date, end_date=end_date,
        owner_user_id=owner_user_id if current_user.is_superuser else None,
    )
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["metric", "value"])
    for key, value in (stats or {}).items():
        if isinstance(value, (str, int, float)) or value is None:
            writer.writerow([key, value])
    return PlainTextResponse(output.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=detection-statistics.csv"})


@router.get("/{task_id}", response_model=DetectionTaskDetail)
def get_history_detail(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """检测任务详情，含所有检测结果"""
    task = history_service.get_task_detail(db, task_id, current_user.id, current_user.is_superuser)
    minio = MinIOClient()
    return {
        "task": _task_to_response(task),
        "results": [_result_to_response(r, minio) for r in task.results],
    }


@router.delete("/{task_id}")
def delete_history(
    task_id: int,
    http_request: Request,
    confirmation_id: str | None = Header(default=None, alias="X-Confirmation-ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """隐藏检测任务；撤销窗口后清理 MinIO 结果和数据库记录。"""
    action_confirmation_service.require_or_prepare(
        db, confirmation_uuid=confirmation_id, user_id=current_user.id,
        operation="delete_task", target_type="detection_task", target_id=str(task_id),
        impact={"scope": "hide one detection task and its stored results during the undo window", "reversible": True},
        payload={}, request_id=getattr(http_request.state, "request_id", None),
    )
    task = db.query(DetectionTask).filter(DetectionTask.id == task_id).first()
    if task is None:
        return {"message": "deleted"}
    if task.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="无权删除该记录")
    if task.status == "deleted":
        raise HTTPException(status_code=404, detail="检测任务不存在")
    previous_status = task.status
    task.status = "deleted"
    db.commit()
    undo_id = undo_service.create(db, current_user.id, "delete_detection_task", {
        "task_id": task.id,
        "previous_status": previous_status,
    }).undo_uuid
    operation_log_service.record(
        db, user=current_user, module="detection", action="delete_task",
        target_type="detection_task", target_id=str(task_id),
        description=f"delete detection task id={task_id}", request=http_request,
    )
    return {"message": "deleted", "undo_id": undo_id}


def export_history(
    scene_id: int | None = None,
    task_type: str | None = None,
    status: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    *,
    media_type: str | None = None,
    keyword: str | None = None,
    owner_user_id: int | None = None,
):
    items, _ = history_service.list_tasks(
        db, user_id=current_user.id, is_superuser=current_user.is_superuser,
        scene_id=scene_id, task_type=task_type, status=status,
        start_date=start_date, end_date=end_date, media_type=media_type,
        keyword=keyword, owner_user_id=owner_user_id, page=1, page_size=5000,
    )
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["task_id", "scene", "task_type", "status", "images", "defects", "inference_ms", "created_at"])
    for item in items:
        writer.writerow([
            item.id, item.scene.display_name if item.scene else "", item.task_type,
            item.status, item.total_images, item.total_objects,
            item.total_inference_time, item.created_at.isoformat() if item.created_at else "",
        ])
    return PlainTextResponse(output.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=detection-history.csv"})


@router.post("/{task_id}/restore", response_model=DetectionTaskResponse)
def restore_history(
    task_id: int,
    expected_version: int | None = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    can_delete_all = authorization_service.has_permission(db, current_user, "detection:task:delete_all")
    task = history_service.restore_task(
        db, task_id, current_user.id, can_delete_all, expected_version=expected_version
    )
    return _task_to_response(task)


@router.delete("/{task_id}/purge")
def purge_history(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    can_delete_all = authorization_service.has_permission(db, current_user, "detection:task:delete_all")
    job = history_service.purge_task(db, task_id, current_user.id, can_delete_all)
    return {"message": "已彻底删除", "cleanup_job_id": job.id, "status": job.status}



@router.post("/{task_id}/trash")
def trash_delete_history(
    task_id: int,
    http_request: Request,
    expected_version: int | None = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """将检测任务移入 30 天回收站；不会立即删除对象存储文件。"""
    can_delete_all = authorization_service.has_permission(db, current_user, "detection:task:delete_all")
    task = history_service.delete_task(
        db, task_id, current_user.id, can_delete_all, expected_version=expected_version
    )
    operation_log_service.record(
        db, user=current_user, module="detection", action="delete_task",
        target_type="detection_task", target_id=str(task_id),
        description=f"检测任务进入回收站 public_task_id={task.public_task_id}", request=http_request,
    )
    return {
        "message": "已移入回收站",
        "public_task_id": task.public_task_id,
        "resource_version": task.resource_version,
        "purge_after": task.purge_after,
    }
