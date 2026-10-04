"""
检测记录与统计服务层
处理检测任务的创建、状态更新、详情查询、分页历史、筛选、删除和统计
对应任务文档步骤 9。检测本身（跑 YOLO 推理）由后端 B 负责，这里只负责数据落库和查询。
"""
from datetime import date, datetime, time, timedelta

from fastapi import HTTPException
from sqlalchemy import cast, func, or_, String
from sqlalchemy.exc import IntegrityError
from app.services.resource_lifecycle_service import resource_lifecycle_service
from sqlalchemy.orm import Session

from app.entity.db_models import DetectionTask, DetectionResult, DetectionScene, TrainingTask
from app.storage.minio_client import MinIOClient
from app.services.notification_service import notification_service


class HistoryService:
    """检测记录与统计服务"""

    # ── 创建 / 状态更新 ──────────────────────────────────

    @staticmethod
    def create_task(
        db: Session,
        user_id: int,
        scene_id: int,
        task_type: str,
        model_version_id: int | None = None,
        conf_threshold: float = 0.25,
        iou_threshold: float = 0.45,
        image_size: int = 640,
        idempotency_key: str | None = None,
    ) -> DetectionTask:
        """创建检测任务，初始状态为 pending"""
        scene = db.query(DetectionScene).filter(DetectionScene.id == scene_id).first()
        if not scene:
            raise HTTPException(status_code=404, detail="检测场景不存在")

        if idempotency_key:
            existing = db.query(DetectionTask).filter(
                DetectionTask.user_id == user_id,
                DetectionTask.idempotency_key == idempotency_key,
            ).first()
            if existing:
                raise HTTPException(status_code=409, detail={
                    "code": "duplicate_request",
                    "public_task_id": existing.public_task_id,
                    "status": existing.status,
                })

        task = DetectionTask(
            user_id=user_id,
            scene_id=scene_id,
            model_version_id=model_version_id,
            task_type=task_type,
            status="pending",
            conf_threshold=conf_threshold,
            iou_threshold=iou_threshold,
            image_size=image_size,
            idempotency_key=idempotency_key,
        )
        try:
            db.add(task)
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            existing = db.query(DetectionTask).filter(
                DetectionTask.user_id == user_id,
                DetectionTask.idempotency_key == idempotency_key,
            ).first()
            if existing:
                raise HTTPException(status_code=409, detail={
                    "code": "duplicate_request",
                    "public_task_id": existing.public_task_id,
                    "status": existing.status,
                }) from exc
            raise
        db.refresh(task)
        return task

    @staticmethod
    def mark_processing(db: Session, task_id: int) -> DetectionTask:
        task = HistoryService._get_task_or_404(db, task_id)
        task.status = "processing"
        db.commit()
        db.refresh(task)
        return task

    @staticmethod
    def mark_completed(
        db: Session,
        task_id: int,
        total_images: int,
        total_objects: int,
        total_inference_time: float,
    ) -> DetectionTask:
        task = HistoryService._get_task_or_404(db, task_id)
        task.status = "completed"
        task.total_images = total_images
        task.total_objects = total_objects
        task.total_inference_time = total_inference_time
        task.completed_at = datetime.now()
        db.commit()
        db.refresh(task)
        notification_service.create(
            db, task.user_id, "detection_completed", "Detection completed",
            f"Detection task {task.id} completed with {total_objects} detected objects.",
            task_id=task.id, resource_type="detection_task", resource_id=task.id,
        )
        return task

    @staticmethod
    def mark_failed(db: Session, task_id: int, error_message: str) -> DetectionTask:
        task = HistoryService._get_task_or_404(db, task_id)
        task.status = "failed"
        task.error_message = error_message
        task.completed_at = datetime.now()
        db.commit()
        db.refresh(task)
        notification_service.create(
            db, task.user_id, "detection_failed", "Detection failed",
            f"Detection task {task.id} failed.", task_id=task.id,
            resource_type="detection_task", resource_id=task.id,
        )
        return task

    @staticmethod
    def add_results(db: Session, task_id: int, results: list[dict]) -> list[DetectionResult]:
        """
        批量写入某个检测任务下的单目标检测结果。
        results 形如 [{"image_path": ..., "annotated_image_url": ..., "class_name": ...,
                        "class_id": 0, "confidence": 0.9, "bbox": [x1,y1,x2,y2], ...}, ...]
        """
        HistoryService._get_task_or_404(db, task_id)
        objs = [DetectionResult(task_id=task_id, **r) for r in results]
        db.add_all(objs)
        db.commit()
        for o in objs:
            db.refresh(o)
        return objs

    # ── 查询 ─────────────────────────────────────────────

    @staticmethod
    def _apply_task_filters(query, user_id, is_superuser=False, scene_id=None, task_type=None,
                            status=None, start_date=None, end_date=None, media_type=None,
                            keyword=None, owner_user_id=None):
        """Apply the shared history/dashboard visibility and filter contract."""
        query = query.filter(DetectionTask.status != "deleted", DetectionTask.deletion_status == "active")
        if not is_superuser:
            query = query.filter(DetectionTask.user_id == user_id)
        elif owner_user_id is not None:
            query = query.filter(DetectionTask.user_id == owner_user_id)
        if scene_id is not None:
            query = query.filter(DetectionTask.scene_id == scene_id)
        if task_type:
            query = query.filter(DetectionTask.task_type == task_type)
        if media_type:
            media_types = {
                "image": ("single", "batch", "zip"),
                "video": ("video",),
                "frame": ("camera",),
            }.get(media_type)
            if media_types:
                query = query.filter(DetectionTask.task_type.in_(media_types))
        if status:
            query = query.filter(DetectionTask.status == status)
        if start_date:
            query = query.filter(DetectionTask.created_at >= datetime.combine(start_date, time.min))
        if end_date:
            query = query.filter(DetectionTask.created_at < datetime.combine(end_date + timedelta(days=1), time.min))
        if keyword:
            pattern = f"%{keyword.strip()}%"
            query = query.filter(or_(
                cast(DetectionTask.id, String).ilike(pattern),
                DetectionTask.task_type.ilike(pattern),
                DetectionTask.scene.has(or_(
                    DetectionScene.name.ilike(pattern),
                    DetectionScene.display_name.ilike(pattern),
                )),
                DetectionTask.results.any(DetectionResult.image_path.ilike(pattern)),
            ))
        return query

    @staticmethod
    def _get_task_or_404(db: Session, task_id: int) -> DetectionTask:
        task = db.query(DetectionTask).filter(DetectionTask.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="检测任务不存在")
        return task

    @staticmethod
    def get_task_detail(
        db: Session,
        task_id: int,
        user_id: int,
        is_superuser: bool = False,
        include_deleted: bool = False,
    ) -> DetectionTask:
        """获取任务详情，非管理员只能查看自己的记录"""
        task = HistoryService._get_task_or_404(db, task_id)
        if task.status == "deleted":
            raise HTTPException(status_code=404, detail="检测任务不存在")
        if task.user_id != user_id and not is_superuser:
            raise HTTPException(status_code=403, detail="无权访问该记录")
        if task.deletion_status != "active" and not include_deleted:
            raise HTTPException(status_code=404, detail="检测任务不存在")
        return task

    @staticmethod
    def list_tasks(
        db: Session,
        user_id: int,
        is_superuser: bool = False,
        scene_id: int | None = None,
        task_type: str | None = None,
        status: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        page: int = 1,
        page_size: int = 20,
        media_type: str | None = None,
        keyword: str | None = None,
        owner_user_id: int | None = None,
    ) -> tuple[list[DetectionTask], int]:
        """分页历史查询，支持按场景/类型/状态筛选；非管理员只能看到自己的记录"""
        query = HistoryService._apply_task_filters(
            db.query(DetectionTask), user_id, is_superuser, scene_id, task_type,
            status, start_date, end_date, media_type, keyword, owner_user_id,
        )

        total = query.count()
        items = (
            query.order_by(DetectionTask.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    # ── 删除 ─────────────────────────────────────────────

    @staticmethod
    def delete_task(
        db: Session,
        task_id: int,
        user_id: int,
        is_superuser: bool = False,
        expected_version: int | None = None,
    ) -> DetectionTask:
        """Move a detection task to the recoverable trash."""
        task = HistoryService._get_task_or_404(db, task_id)
        if task.user_id != user_id and not is_superuser:
            raise HTTPException(status_code=403, detail="无权删除该记录")
        return resource_lifecycle_service.trash_detection_task(
            db, task, deleted_by_id=user_id, expected_version=expected_version
        )

    @staticmethod
    def restore_task(
        db: Session,
        task_id: int,
        user_id: int,
        is_superuser: bool = False,
        expected_version: int | None = None,
    ) -> DetectionTask:
        task = HistoryService._get_task_or_404(db, task_id)
        if task.user_id != user_id and not is_superuser:
            raise HTTPException(status_code=403, detail="无权恢复该记录")
        return resource_lifecycle_service.restore_detection_task(db, task, expected_version)

    @staticmethod
    def purge_task(db: Session, task_id: int, user_id: int, is_superuser: bool = False):
        task = HistoryService._get_task_or_404(db, task_id)
        if task.user_id != user_id and not is_superuser:
            raise HTTPException(status_code=403, detail="无权彻底删除该记录")
        return resource_lifecycle_service.purge_detection_task(db, task)

    # ── 统计 ─────────────────────────────────────────────

    @staticmethod
    def get_statistics(db: Session, user_id: int, is_superuser: bool = False, days: int = 30,
                       scene_id: int | None = None, task_type: str | None = None,
                       status: str | None = None, start_date: date | None = None,
                       end_date: date | None = None, media_type: str | None = None,
                       keyword: str | None = None, owner_user_id: int | None = None) -> dict:
        """Statistics use history filters; absent status means completed tasks only."""
        if not start_date and not end_date:
            start_date = (datetime.now() - timedelta(days=days - 1)).date()
        start_date = start_date or end_date
        end_date = end_date or date.today()
        effective_status = status or "completed"
        query = HistoryService._apply_task_filters(
            db.query(DetectionTask), user_id, is_superuser, scene_id, task_type,
            effective_status, start_date, end_date, media_type, keyword, owner_user_id,
        )
        if not is_superuser:
            query = query.filter(DetectionTask.user_id == user_id)

        total_tasks = query.count()
        total_images = query.with_entities(func.coalesce(func.sum(DetectionTask.total_images), 0)).scalar()
        total_objects = query.with_entities(func.coalesce(func.sum(DetectionTask.total_objects), 0)).scalar()
        avg_time = query.with_entities(func.coalesce(func.avg(DetectionTask.total_inference_time), 0)).scalar()

        # 类别分布：基于 detection_results 按 class_name 聚合
        result_query = HistoryService._apply_task_filters(
            db.query(func.coalesce(DetectionResult.class_name_cn, DetectionResult.class_name).label('display_name'), func.count(DetectionResult.id)).join(
                DetectionTask, DetectionResult.task_id == DetectionTask.id
            ).filter(DetectionResult.class_name != ""),
            user_id, is_superuser, scene_id, task_type, effective_status, start_date, end_date,
            media_type, keyword, owner_user_id,
        )
        class_distribution = {name: int(cnt) for name, cnt in result_query.group_by('display_name').all()}

        daily_query = HistoryService._apply_task_filters(
            db.query(func.date(DetectionTask.created_at), func.count(DetectionTask.id)),
            user_id, is_superuser, scene_id, task_type, effective_status, start_date, end_date,
            media_type, keyword, owner_user_id,
        )
        daily_rows = daily_query.group_by(func.date(DetectionTask.created_at)).order_by(func.date(DetectionTask.created_at)).all()
        daily_counts = {str(d): int(c) for d, c in daily_rows}
        daily_trend = [{"date": str(day), "count": daily_counts.get(str(day), 0)}
                       for offset in range((end_date - start_date).days + 1)
                       for day in [start_date + timedelta(days=offset)]]

        # 每天检测耗时：按已持久化的任务总耗时聚合。
        # DetectionResult 是“每个缺陷一行”，不能作为图片/任务样本：
        # 无缺陷图片没有结果行，批量任务还会因多个缺陷重复计数。
        time_query = HistoryService._apply_task_filters(
            db.query(func.date(DetectionTask.created_at),
                     func.min(DetectionTask.total_inference_time),
                     func.max(DetectionTask.total_inference_time),
                     func.avg(DetectionTask.total_inference_time)),
            user_id, is_superuser, scene_id, task_type, effective_status, start_date, end_date,
        )
        time_rows = time_query.group_by(func.date(DetectionTask.created_at)).order_by(func.date(DetectionTask.created_at)).all()
        time_map = {str(d): {"min": float(mn or 0), "max": float(mx or 0), "avg": float(av or 0)} for d, mn, mx, av in time_rows}
        daily_inference_time = [{"date": str(day), **time_map.get(str(day), {"min": 0, "max": 0, "avg": 0})}
                                for offset in range((end_date - start_date).days + 1)
                                for day in [start_date + timedelta(days=offset)]]

        # 场景分布
        scene_query = query.join(DetectionScene, DetectionTask.scene_id == DetectionScene.id).with_entities(
            DetectionScene.display_name, func.count(DetectionTask.id)
        )
        scene_distribution = dict(scene_query.group_by(DetectionScene.display_name).all())

        training_query = db.query(TrainingTask)
        if not is_superuser:
            training_query = training_query.filter(TrainingTask.user_id == user_id)
        training_query = training_query.filter(TrainingTask.created_at >= datetime.combine(start_date, time.min))
        training_query = training_query.filter(TrainingTask.created_at < datetime.combine(end_date + timedelta(days=1), time.min))
        training_rows = training_query.with_entities(func.date(TrainingTask.created_at), func.count(TrainingTask.id)).group_by(func.date(TrainingTask.created_at)).all()
        training_counts = {str(d): int(c) for d, c in training_rows}
        training_daily_trend = [{"date": str(day), "count": training_counts.get(str(day), 0)}
                                for offset in range((end_date - start_date).days + 1)
                                for day in [start_date + timedelta(days=offset)]]

        return {
            "total_tasks": total_tasks,
            "total_images": int(total_images),
            "total_objects": int(total_objects),
            "avg_inference_time": float(avg_time),
            "class_distribution": class_distribution,
            "daily_trend": daily_trend,
            "scene_distribution": scene_distribution,
            "training_total_tasks": training_query.count(),
            "training_daily_trend": training_daily_trend,
            "daily_inference_time": daily_inference_time,
        }


# 全局单例
history_service = HistoryService()
