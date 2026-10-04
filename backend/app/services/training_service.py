"""
LEGACY COMPATIBILITY MODULE

The production API imports ``app.training.training_service``. This module is
kept only for existing tests and older integrations; new callers must use the
canonical training service and API adapters.

训练任务与模型版本服务层
处理训练任务的创建、进度/指标更新、生命周期状态，以及训练产出的模型版本管理
对应任务文档步骤 11 的训练部分。
"""
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.entity.db_models import TrainingTask, TrainingMetric, ModelVersion, DetectionScene
from app.services.notification_service import notification_service


class TrainingService:
    """训练任务服务"""

    # ── 训练任务生命周期 ─────────────────────────────────

    @staticmethod
    def create_task(
        db: Session,
        user_id: int,
        scene_id: int,
        model_name: str = "yolov11n",
        epochs: int = 100,
        img_size: int = 640,
        batch_size: int = 16,
        device: str = "0",
        optimizer: str = "SGD",
        lr0: float = 0.01,
        augment_config: dict | None = None,
        dataset_path: str | None = None,
        data_yaml: str | None = None,
        dataset_size: int | None = None,
    ) -> TrainingTask:
        scene = db.query(DetectionScene).filter(DetectionScene.id == scene_id).first()
        if not scene:
            raise HTTPException(status_code=404, detail="检测场景不存在")

        task = TrainingTask(
            user_id=user_id,
            scene_id=scene_id,
            task_uuid=str(uuid.uuid4()),
            status="pending",
            model_name=model_name,
            epochs=epochs,
            img_size=img_size,
            batch_size=batch_size,
            device=device,
            optimizer=optimizer,
            lr0=lr0,
            augment_config=augment_config,
            dataset_path=dataset_path,
            data_yaml=data_yaml,
            dataset_size=dataset_size,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task

    @staticmethod
    def _get_task_or_404(db: Session, task_id: int) -> TrainingTask:
        task = db.query(TrainingTask).filter(TrainingTask.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="训练任务不存在")
        return task

    @staticmethod
    def start_task(db: Session, task_id: int) -> TrainingTask:
        task = TrainingService._get_task_or_404(db, task_id)
        task.status = "running"
        task.started_at = datetime.now()
        db.commit()
        db.refresh(task)
        return task

    @staticmethod
    def record_epoch_metric(
        db: Session,
        task_id: int,
        epoch: int,
        box_loss: float | None = None,
        cls_loss: float | None = None,
        dfl_loss: float | None = None,
        precision: float | None = None,
        recall: float | None = None,
        map50: float | None = None,
        map50_95: float | None = None,
        lr: float | None = None,
    ) -> TrainingMetric:
        """
        每个 epoch 结束时调用一次，写入 training_metrics 用于绘制训练曲线，
        同时同步更新 training_tasks 的 current_epoch/progress。
        细粒度的实时进度（batch 级别）应写 Redis，不要打这张表。
        """
        task = TrainingService._get_task_or_404(db, task_id)

        metric = TrainingMetric(
            task_id=task_id, epoch=epoch, box_loss=box_loss, cls_loss=cls_loss, dfl_loss=dfl_loss,
            precision=precision, recall=recall, map50=map50, map50_95=map50_95, lr=lr,
        )
        db.add(metric)

        task.current_epoch = epoch
        if task.epochs:
            task.progress = min(100, round(epoch / task.epochs * 100))

        db.commit()
        db.refresh(metric)
        return metric

    @staticmethod
    def complete_task(db: Session, task_id: int) -> TrainingTask:
        task = TrainingService._get_task_or_404(db, task_id)
        task.status = "completed"
        task.progress = 100
        task.completed_at = datetime.now()
        db.commit()
        db.refresh(task)
        notification_service.create(
            db, task.user_id, "training_completed", "Training completed",
            f"Training task {task.task_uuid} completed.", task_id=task.task_uuid,
            resource_type="training_task", resource_id=task.id,
        )
        return task

    @staticmethod
    def fail_task(db: Session, task_id: int, error_message: str) -> TrainingTask:
        task = TrainingService._get_task_or_404(db, task_id)
        task.status = "failed"
        task.error_message = error_message
        task.completed_at = datetime.now()
        db.commit()
        db.refresh(task)
        notification_service.create(
            db, task.user_id, "training_failed", "Training failed",
            f"Training task {task.task_uuid} failed.", task_id=task.task_uuid,
            resource_type="training_task", resource_id=task.id,
        )
        return task

    @staticmethod
    def list_metrics(db: Session, task_id: int) -> list[TrainingMetric]:
        return (
            db.query(TrainingMetric)
            .filter(TrainingMetric.task_id == task_id)
            .order_by(TrainingMetric.epoch.asc())
            .all()
        )

    @staticmethod
    def list_tasks_by_user(db: Session, user_id: int, is_superuser: bool = False) -> list[TrainingTask]:
        query = db.query(TrainingTask)
        if not is_superuser:
            query = query.filter(TrainingTask.user_id == user_id)
        return query.order_by(TrainingTask.created_at.desc()).all()

    # ── 模型版本管理 ─────────────────────────────────────

    @staticmethod
    def create_model_version(
        db: Session,
        scene_id: int,
        version: str,
        model_name: str,
        model_path: str,
        training_task_id: int | None = None,
        model_type: str = "yolov11n",
        minio_url: str | None = None,
        map50: float | None = None,
        map50_95: float | None = None,
        precision: float | None = None,
        recall: float | None = None,
        per_class_ap: dict | None = None,
        description: str | None = None,
        file_size: int | None = None,
    ) -> ModelVersion:
        """训练完成后产出模型版本，或手动上传模型时调用"""
        model = ModelVersion(
            scene_id=scene_id,
            training_task_id=training_task_id,
            version=version,
            model_name=model_name,
            model_type=model_type,
            model_path=model_path,
            minio_url=minio_url,
            map50=map50,
            map50_95=map50_95,
            precision=precision,
            recall=recall,
            per_class_ap=per_class_ap,
            description=description,
            file_size=file_size,
        )
        db.add(model)
        db.commit()
        db.refresh(model)
        return model

    @staticmethod
    def list_model_versions(db: Session, scene_id: int) -> list[ModelVersion]:
        return (
            db.query(ModelVersion)
            .filter(ModelVersion.scene_id == scene_id, ModelVersion.status != "deleted")
            .order_by(ModelVersion.created_at.desc())
            .all()
        )

    @staticmethod
    def archive_model_version(db: Session, model_version_id: int) -> ModelVersion:
        """归档模型版本（软删除，避免破坏历史检测记录对它的引用）"""
        model = db.query(ModelVersion).filter(ModelVersion.id == model_version_id).first()
        if not model:
            raise HTTPException(status_code=404, detail="模型版本不存在")
        model.status = "archived"
        if model.is_default:
            model.is_default = False
        db.commit()
        db.refresh(model)
        return model


# 全局单例
training_service = TrainingService()
