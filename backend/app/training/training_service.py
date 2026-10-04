"""
模型训练服务

职责：
  - 封装 YOLOv11 训练启动、监控、停止逻辑
  - 支持本地 CPU 训练和 GPU 训练
  - 训练在后台线程中执行，不阻塞 API 请求
  - 实时解析训练指标并写入数据库
  - 解析 Ultralytics 生成的 results.csv 获取训练日志

使用方式：
  from app.training.training_service import training_service

  # 启动训练
  task = training_service.start_training(
      db=db,
      user_id=current_user.id,
      scene_id=scene.id,
      config={"model_name": "yolo11n", "epochs": 50, "batch_size": 8}
  )

  # 查询训练状态
  status = training_service.get_training_status(db, task_id)

  # 获取训练指标
  metrics = training_service.get_training_metrics(db, task_id)
"""

import csv
import os
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timedelta
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from pathlib import Path

import yaml

from app.config.settings import settings
from app.core.logger import get_logger
from app.database.session import SessionLocal
from app.entity.db_models import ModelVersion, TrainingMetric, TrainingTask
from app.services.notification_service import notification_service
from app.entity.schemas import AdvancedTrainingConfig

logger = get_logger(__name__)

# ── 训练进程注册表 ────────────────────────────────────
# 存储正在运行的训练任务的 model 引用，用于中途停止训练
# key: task_uuid, value: YOLO model 实例
_running_tasks: dict = {}
_stop_requested: set[str] = set()
_running_lock = threading.Lock()


class TrainingCancelled(RuntimeError):
    """Controlled exception used to leave Ultralytics' batch loop immediately."""


def _ensure_training_not_cancelled(db, task: TrainingTask, task_uuid: str) -> None:
    """Raise when cancellation was requested in this or another API process."""
    with _running_lock:
        requested_in_process = task_uuid in _stop_requested
    try:
        db.refresh(task, attribute_names=["status"])
    except Exception:
        db.rollback()
        raise
    if requested_in_process or task.status == "cancelled":
        raise TrainingCancelled(task_uuid)


def _create_runtime_data_yaml(source_path: str) -> str:
    """Create an isolated training config with paths rooted at its dataset.

    Uploaded datasets are user assets.  Training must never rewrite their
    ``data.yaml`` just to make relative image paths work, especially when a
    legacy archive contains a stale absolute ``path`` value.
    """
    with open(source_path, "r", encoding="utf-8") as source:
        config = yaml.safe_load(source) or {}
    if not isinstance(config, dict):
        raise ValueError("data.yaml 必须是对象")

    config["path"] = os.path.dirname(os.path.abspath(source_path))
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".yaml", prefix="ssdd-training-",
        delete=False,
    ) as runtime_file:
        yaml.safe_dump(config, runtime_file, allow_unicode=True, sort_keys=False)
        return runtime_file.name


class TrainingService:
    """模型训练服务 — 封装 YOLOv11 训练全流程"""

    @staticmethod
    def start_training(
        db,
        user_id: int,
        scene_id: int,
        config: dict,
    ) -> TrainingTask:
        """
        创建并启动训练任务

        流程：
          1. 在数据库中创建 TrainingTask 记录（状态 pending）
          2. 启动后台守护线程执行 _run_training()
          3. 立即返回任务对象（前端通过轮询获取进度）

        Args:
            db: SQLAlchemy 数据库会话
            user_id: 操作用户 ID
            scene_id: 关联的检测场景 ID
            config: 训练配置字典，支持的字段：
                - model_name: 基础模型名称（yolo11n/s/m/l/x）
                - epochs: 训练轮数
                - img_size: 图像尺寸
                - batch_size: 批次大小
                - device: 训练设备（cpu / 0 / 1）
                - optimizer: 优化器（SGD / Adam / AdamW）
                - lr0: 初始学习率
                - augment_config: 数据增强配置
                - dataset_path: 数据集路径（可选，默认使用场景目录）
                - data_yaml: data.yaml 路径（可选，自动查找）

        Returns:
            创建的 TrainingTask 数据库对象
        """
        raw_train_config = config.get("train_config") or {}
        if raw_train_config:
            config = dict(config)
            config["train_config"] = AdvancedTrainingConfig.model_validate(raw_train_config).model_dump(exclude_none=True)

        # ── 生成唯一任务标识 ──
        task_uuid = str(uuid.uuid4())[:8]
        idempotency_key = config.get("idempotency_key")
        if idempotency_key:
            existing = db.query(TrainingTask).filter(
                TrainingTask.user_id == user_id,
                TrainingTask.idempotency_key == idempotency_key,
            ).first()
            if existing:
                raise HTTPException(status_code=409, detail={
                    "code": "duplicate_request",
                    "public_task_id": existing.public_task_id,
                    "status": existing.status,
                })

        # ── 查找 data.yaml ──
        data_yaml = config.get("data_yaml")
        dataset_path = config.get("dataset_path", "")
        if not data_yaml and dataset_path:
            # 在数据集目录下查找 data.yaml
            yaml_candidate = os.path.join(dataset_path, "data.yaml")
            if os.path.exists(yaml_candidate):
                data_yaml = yaml_candidate

        # ── 创建数据库记录 ──
        task = TrainingTask(
            user_id=user_id,
            scene_id=scene_id,
            task_uuid=task_uuid,
            status="pending",
            model_name=config.get("model_name", "yolo11n"),
            epochs=config.get("epochs", 50),
            img_size=config.get("img_size", 640),
            batch_size=config.get("batch_size", 8),
            device=config.get("device", "cpu"),
            optimizer=config.get("optimizer", "SGD"),
            lr0=config.get("lr0", 0.01),
            augment_config=config.get("augment_config"),
            train_config=config.get("train_config") or {},
            dataset_path=dataset_path,
            data_yaml=data_yaml,
            dataset_size=config.get("dataset_size"),
            idempotency_key=idempotency_key,
        )
        try:
            db.add(task)
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            existing = db.query(TrainingTask).filter(
                TrainingTask.user_id == user_id,
                TrainingTask.idempotency_key == idempotency_key,
            ).first()
            if existing:
                raise HTTPException(status_code=409, detail={
                    "code": "duplicate_request",
                    "public_task_id": existing.public_task_id,
                    "status": existing.status,
                }) from exc
            raise
        db.refresh(task)

        # ── 启动后台训练线程 ──
        thread = threading.Thread(
            target=TrainingService._run_training,
            args=(task.id, task.task_uuid, config),
            daemon=True,  # 守护线程：主进程退出时自动结束
            name=f"train-{task_uuid}",
        )
        thread.start()

        logger.info(
            "训练任务已启动：task_id=%d, uuid=%s, model=%s, epochs=%d",
            task.id,
            task_uuid,
            task.model_name,
            task.epochs,
        )
        return task

    @staticmethod
    def _run_training(task_id: int, task_uuid: str, config: dict):
        """
        在后台线程中执行 YOLOv11 训练（内部方法）

        流程：
          1. 更新任务状态为 running
          2. 加载预训练模型
          3. 调用 model.train() 开始训练
          4. 训练完成后解析结果，更新状态为 completed
          5. 异常时更新状态为 failed

        Args:
            task_id: 训练任务数据库 ID
            task_uuid: 任务唯一标识
            config: 训练配置字典
        """
        # ── 创建独立的数据库会话（后台线程不能复用请求级会话）──
        db = SessionLocal()
        runtime_data_yaml = None
        original_cwd = os.getcwd()
        try:
            task = db.query(TrainingTask).filter(TrainingTask.id == task_id).first()
            if not task:
                logger.error("训练任务不存在：task_id=%d", task_id)
                return
            if task.status == "cancelled":
                return

            # ── 更新状态为 running ──
            task.status = "running"
            task.started_at = datetime.now()
            db.commit()

            # ── 导入 ultralytics ──
            from ultralytics import YOLO

            # ── 加载预训练模型 ──
            model_name = config.get("model_name", "yolo11n")
            logger.info("加载预训练模型：%s（首次使用将自动下载）", model_name)
            model = YOLO(model_name)

            # ── 注册到运行中任务表（用于中途停止）──
            with _running_lock:
                _running_tasks[task_uuid] = model
                stop_requested = task_uuid in _stop_requested
            if stop_requested:
                return

            # ── 确定 data.yaml 路径 ──
            data_yaml = config.get("data_yaml", "")
            if not data_yaml:
                dataset_path = config.get("dataset_path", "")
                data_yaml = os.path.join(dataset_path, "data.yaml")

            if not os.path.exists(data_yaml):
                raise FileNotFoundError(f"data.yaml 不存在：{data_yaml}")

            runtime_data_yaml = _create_runtime_data_yaml(data_yaml)
            logger.info("创建训练运行时 data.yaml：%s", runtime_data_yaml)

            train_kwargs = {
                "data": runtime_data_yaml,
                "epochs": config.get("epochs", 50),
                "imgsz": config.get("img_size", 640),
                "batch": config.get("batch_size", 8),
                "device": config.get("device", "cpu"),
                "optimizer": config.get("optimizer", "SGD"),
                "lr0": config.get("lr0", 0.01),
                "project": os.path.join(original_cwd, settings.TRAIN_OUTPUT_DIR),
                "name": f"task_{task_uuid}",
                "exist_ok": True,
                "verbose": True,
                "save": True,
                "plots": False,
            }
            # Advanced options were validated by ``TrainingTaskCreate``.  They
            # cannot override protected paths or core task fields because the
            # schema exposes only Ultralytics training knobs.
            train_kwargs.update(config.get("train_config") or {})

            # ── 注册训练回调：每个 epoch 结束时更新数据库 ──
            def on_train_epoch_end(trainer):
                """训练 epoch 结束时的回调"""
                try:
                    # 从 trainer 获取当前 epoch 指标
                    epoch = trainer.epoch + 1  # ultralytics epoch 从 0 开始
                    metrics = trainer.metrics or {}
                    loss_items = (
                        trainer.loss_items if hasattr(trainer, "loss_items") else {}
                    )

                    metric_record = TrainingMetric(
                        task_id=task_id,
                        epoch=epoch,
                        box_loss=float(
                            metrics.get("metrics/box_loss", 0)
                            if isinstance(metrics, dict)
                            else 0
                        ),
                        cls_loss=float(
                            metrics.get("metrics/cls_loss", 0)
                            if isinstance(metrics, dict)
                            else 0
                        ),
                        dfl_loss=float(
                            metrics.get("metrics/dfl_loss", 0)
                            if isinstance(metrics, dict)
                            else 0
                        ),
                        precision=float(
                            metrics.get("metrics/precision(B)", 0)
                            if isinstance(metrics, dict)
                            else 0
                        ),
                        recall=float(
                            metrics.get("metrics/recall(B)", 0)
                            if isinstance(metrics, dict)
                            else 0
                        ),
                        map50=float(
                            metrics.get("metrics/mAP50(B)", 0)
                            if isinstance(metrics, dict)
                            else 0
                        ),
                        map50_95=float(
                            metrics.get("metrics/mAP50-95(B)", 0)
                            if isinstance(metrics, dict)
                            else 0
                        ),
                    )
                    db.add(metric_record)

                    # 更新任务进度
                    total_epochs = config.get("epochs", 50)
                    task.current_epoch = epoch
                    task.progress = int((epoch / total_epochs) * 100)
                    db.commit()

                    logger.debug(
                        "训练进度：task=%s epoch=%d/%d box_loss=%.4f",
                        task_uuid,
                        epoch,
                        total_epochs,
                        metric_record.box_loss or 0,
                    )
                except Exception as e:
                    logger.warning("训练回调异常（不影响训练）：%s", str(e))
                    db.rollback()

            def on_train_batch_end(trainer):
                """Persist coarse batch progress so the monitor moves during long epochs."""
                _ensure_training_not_cancelled(db, task, task_uuid)
                try:
                    total_batches = max(int(getattr(trainer, "nb", 0) or 0), 1)
                    batch_index = int(getattr(trainer, "batch_i", 0) or 0) + 1
                    epoch = int(getattr(trainer, "epoch", 0) or 0)
                    task.progress = min(99, int((epoch + batch_index / total_batches) * 100 / max(task.epochs, 1)))
                    if batch_index == 1 or batch_index % 10 == 0:
                        db.commit()
                except Exception:
                    db.rollback()

            model.add_callback("on_train_batch_end", on_train_batch_end)
            # 添加回调
            model.add_callback("on_train_epoch_end", on_train_epoch_end)

            # ── 开始训练（阻塞直到完成）──
            logger.info(
                "开始训练：data=%s, epochs=%d", runtime_data_yaml, train_kwargs["epochs"]
            )
            results = model.train(**train_kwargs)

            # ── 训练完成，解析最终结果 ──
            db.refresh(task)
            if task.status != "cancelled":
                task.status = "completed"
                task.progress = 100
                task.current_epoch = config.get("epochs", 50)
                task.completed_at = datetime.now()
                db.commit()

            # ── 从 results.csv 补充最终指标 ──
            project_path = os.path.join(original_cwd, settings.TRAIN_OUTPUT_DIR)
            TrainingService._parse_final_results(db, task_id, task_uuid, config, project_path)

            logger.info("训练完成：task_id=%d, uuid=%s", task_id, task_uuid)
            if task.status == "completed":
                notification_service.safe_create(
                    db, task.user_id, "training_completed", "训练完成",
                    f"训练任务 {task_uuid} 已完成", task_id=task_id,
                )

        except TrainingCancelled:
            db.rollback()
            task = db.query(TrainingTask).filter(TrainingTask.id == task_id).first()
            if task:
                task.status = "cancelled"
                task.completed_at = task.completed_at or datetime.now()
                db.commit()
            logger.info("训练线程已终止：task_id=%d, uuid=%s", task_id, task_uuid)

        except FileNotFoundError as e:
            logger.error("训练文件缺失：task_id=%d, error=%s", task_id, str(e))
            if task.status != "cancelled":
                task.status = "failed"
                task.error_message = str(e)
                task.completed_at = datetime.now()
                db.commit()
                notification_service.safe_create(
                    db, task.user_id, "training_failed", "训练失败",
                    f"训练任务 {task_uuid} 执行失败", task_id=task_id,
                )

        except Exception as e:
            logger.error(
                "训练异常：task_id=%d, error=%s", task_id, str(e), exc_info=True
            )
            if task.status != "cancelled":
                task.status = "failed"
                task.error_message = str(e)[:2000]  # 限制错误信息长度
                task.completed_at = datetime.now()
                db.commit()
                notification_service.safe_create(
                    db, task.user_id, "training_failed", "训练失败",
                    f"训练任务 {task_uuid} 执行失败", task_id=task_id,
                )

        finally:
            if runtime_data_yaml:
                try:
                    os.unlink(runtime_data_yaml)
                except OSError:
                    pass

            # 恢复工作目录
            try:
                os.chdir(original_cwd)
                logger.info(f"恢复工作目录：{original_cwd}")
            except Exception:
                pass

            with _running_lock:
                _running_tasks.pop(task_uuid, None)
                _stop_requested.discard(task_uuid)
            db.close()

    @staticmethod
    def _parse_final_results(db, task_id: int, task_uuid: str, config: dict, project_path: str = None):
        """
        训练完成后从 results.csv 解析最终指标并补充到数据库

        Ultralytics 在训练过程中会将每个 epoch 的指标写入 results.csv，
        回调中可能遗漏最后几个 epoch，此方法确保数据完整。

        Args:
            db: 数据库会话
            task_id: 训练任务 ID
            task_uuid: 任务 UUID
            config: 训练配置
            project_path: 训练输出目录（绝对路径）
        """
        if project_path is None:
            project_path = settings.TRAIN_OUTPUT_DIR

        results_csv = os.path.join(
            project_path,
            f"task_{task_uuid}",
            "results.csv",
        )

        if not os.path.exists(results_csv):
            logger.warning("results.csv 不存在：%s", results_csv)
            return

        try:
            task = db.query(TrainingTask).filter(TrainingTask.id == task_id).first()
            if task:
                TrainingService._sync_results_csv(db, task)
            logger.info("results.csv 解析完成，指标已补充到数据库")

        except Exception as e:
            logger.warning("results.csv 解析异常（不影响训练结果）：%s", str(e))
            db.rollback()

    @staticmethod
    def _sync_results_csv(db, task: TrainingTask) -> None:
        """Incrementally mirror durable Ultralytics CSV metrics into the database."""
        output_root = os.path.abspath(settings.TRAIN_OUTPUT_DIR)
        results_csv = os.path.join(output_root, f"task_{task.task_uuid}", "results.csv")
        parsed = TrainingService.parse_results_csv(results_csv)
        if not parsed:
            return

        parsed_by_epoch = {values["epoch"]: values for values in parsed}
        existing = {}
        for metric in (
            db.query(TrainingMetric)
            .filter(TrainingMetric.task_id == task.id)
            .order_by(TrainingMetric.id.asc())
            .all()
        ):
            if (
                metric.epoch < 1
                or metric.epoch > task.epochs
                or metric.epoch not in parsed_by_epoch
                or metric.epoch in existing
            ):
                db.delete(metric)
                continue
            existing[metric.epoch] = metric

        metric_fields = (
            "box_loss", "cls_loss", "dfl_loss", "precision", "recall",
            "map50", "map50_95", "lr",
        )
        changed = False
        for values in parsed_by_epoch.values():
            epoch = values["epoch"]
            metric = existing.get(epoch)
            if metric is None:
                metric = TrainingMetric(task_id=task.id, epoch=epoch)
                db.add(metric)
                existing[epoch] = metric
                changed = True
            for field in metric_fields:
                value = values.get(field)
                if value is not None and getattr(metric, field) != value:
                    setattr(metric, field, value)
                    changed = True

        completed_epoch = max(existing)
        bounded_epoch = min(completed_epoch, task.epochs)
        progress = min(100, int(bounded_epoch * 100 / max(task.epochs, 1)))
        if task.current_epoch != bounded_epoch or task.progress != progress:
            task.current_epoch = bounded_epoch
            task.progress = progress
            changed = True
        if changed:
            db.commit()

    @staticmethod
    def get_training_status(db, task_id: int) -> dict:
        """
        获取训练任务状态

        返回任务基本信息 + 当前进度 + 最新指标

        Args:
            db: 数据库会话
            task_id: 训练任务 ID

        Returns:
            状态字典，包含：
                - task: 任务基本信息
                - latest_metric: 最新 epoch 的指标
                - is_running: 是否在运行中
        """
        task = db.query(TrainingTask).filter(TrainingTask.id == task_id).first()
        if not task:
            return {"error": "训练任务不存在"}

        TrainingService._sync_results_csv(db, task)
        db.refresh(task)

        # 获取最新一条指标记录
        latest_metric = (
            db.query(TrainingMetric)
            .filter(TrainingMetric.task_id == task_id)
            .order_by(TrainingMetric.epoch.desc())
            .first()
        )

        # 检查是否在运行中
        with _running_lock:
            is_running = task.task_uuid in _running_tasks

        return {
            "task": {
                "id": task.id,
                "public_task_id": task.public_task_id,
                "task_uuid": task.task_uuid,
                "status": task.status,
                "model_name": task.model_name,
                "epochs": task.epochs,
                "current_epoch": task.current_epoch,
                "progress": task.progress,
                "device": task.device,
                "batch_size": task.batch_size,
                "img_size": task.img_size,
                "optimizer": task.optimizer,
                "lr0": task.lr0,
                "augment_config": task.augment_config,
                "train_config": task.train_config or {},
                "dataset_path": task.dataset_path,
                "dataset_name": os.path.basename(os.path.normpath(task.dataset_path)) if task.dataset_path else None,
                "dataset_size": task.dataset_size,
                "started_at": str(task.started_at) if task.started_at else None,
                "completed_at": str(task.completed_at) if task.completed_at else None,
                "error_message": task.error_message,
            },
            "latest_metric": {
                "epoch": latest_metric.epoch,
                "box_loss": latest_metric.box_loss,
                "cls_loss": latest_metric.cls_loss,
                "dfl_loss": latest_metric.dfl_loss,
                "precision": latest_metric.precision,
                "recall": latest_metric.recall,
                "map50": latest_metric.map50,
                "map50_95": latest_metric.map50_95,
                "lr": latest_metric.lr,
            }
            if latest_metric
            else None,
            "is_running": is_running,
        }

    @staticmethod
    def get_training_metrics(db, task_id: int) -> list:
        """
        获取训练任务的所有 epoch 指标（用于绘制训练曲线）

        Args:
            db: 数据库会话
            task_id: 训练任务 ID

        Returns:
            指标列表，每项包含 epoch 和各项指标值
        """
        task = db.query(TrainingTask).filter(TrainingTask.id == task_id).first()
        if task:
            TrainingService._sync_results_csv(db, task)

        metrics = (
            db.query(TrainingMetric)
            .filter(TrainingMetric.task_id == task_id)
            .order_by(TrainingMetric.epoch.asc())
            .all()
        )

        return [
            {
                "epoch": m.epoch,
                "box_loss": m.box_loss,
                "cls_loss": m.cls_loss,
                "dfl_loss": m.dfl_loss,
                "precision": m.precision,
                "recall": m.recall,
                "map50": m.map50,
                "map50_95": m.map50_95,
                "lr": m.lr,
            }
            for m in metrics
        ]

    @staticmethod
    def build_training_report(db, task_id: int) -> dict:
        """Build a shareable Markdown report from persisted training/evaluation data."""
        task = db.query(TrainingTask).filter(TrainingTask.id == task_id).first()
        if not task:
            return {"error": "training task not found"}
        metrics = TrainingService.get_training_metrics(db, task_id)
        model = db.query(ModelVersion).filter(ModelVersion.training_task_id == task_id).order_by(ModelVersion.id.desc()).first()
        lines = [
            f"# Training report: {task.task_uuid}", "",
            "## Run", f"- Status: {task.status}", f"- Model: {task.model_name}",
            f"- Epochs: {task.current_epoch}/{task.epochs}", f"- Dataset size: {task.dataset_size or '-'}",
            f"- Created: {task.created_at}", f"- Completed: {task.completed_at or '-'}", "",
            "## Evaluation",
        ]
        if model:
            lines.extend([
                f"- Model version: {model.version}",
                f"- mAP@50: {model.map50 if model.map50 is not None else '-'}",
                f"- mAP@50-95: {model.map50_95 if model.map50_95 is not None else '-'}",
                f"- Precision: {model.precision if model.precision is not None else '-'}",
                f"- Recall: {model.recall if model.recall is not None else '-'}",
            ])
            if model.per_class_ap:
                lines.extend(["", "### Per-class AP", "", "| Class | AP50 | AP50-95 |", "|---|---:|---:|"])
                for class_name, values in model.per_class_ap.items():
                    lines.append(f"| {class_name} | {values.get('ap50', '-')} | {values.get('ap50_95', '-')} |")
        else:
            lines.append("Evaluation has not been exported for this run.")
        lines.extend(["", "## Training metrics", "", "| Epoch | Precision | Recall | mAP50 | mAP50-95 |", "|---:|---:|---:|---:|---:|"])
        for metric in metrics:
            lines.append("| {epoch} | {precision} | {recall} | {map50} | {map50_95} |".format(**metric))
        return {"filename": f"training_report_{task.task_uuid}.md", "content": "\n".join(lines) + "\n"}

    @staticmethod
    def stop_training(db, task_id: int) -> dict:
        """
        停止正在运行的训练任务

        通过 ultralytics 的 model.train() 中断机制停止训练

        Args:
            db: 数据库会话
            task_id: 训练任务 ID

        Returns:
            操作结果字典
        """
        task = db.query(TrainingTask).filter(TrainingTask.id == task_id).first()
        if not task:
            return {"error": "训练任务不存在"}

        if task.status not in {"pending", "running"}:
            if task.status == "cancelled":
                return {"message": "训练任务已停止", "task_id": task.id}
            return {"error": f"任务当前状态为 {task.status}，无法停止"}

        with _running_lock:
            _stop_requested.add(task.task_uuid)
            model = _running_tasks.get(task.task_uuid)
            if model:
                # ultralytics 支持通过设置 model.train 的 interrupt 来停止
                try:
                    trainer = getattr(model, "trainer", None)
                    if trainer is not None:
                        trainer.stop = True
                except Exception as e:
                    logger.warning("停止训练异常：%s", str(e))

        # 更新状态
        task.status = "cancelled"
        task.completed_at = datetime.now()
        db.commit()

        logger.info("训练任务已停止：task_id=%d", task_id)
        return {"message": "训练任务已停止", "task_id": task_id}

    @staticmethod
    def get_task_list(db, user_id: int = None, limit: int = 20, is_superuser: bool = False) -> list:
        """
        获取训练任务列表

        Args:
            db: 数据库会话
            user_id: 用户 ID（None 则返回所有用户的任务）
            limit: 返回数量限制

        Returns:
            任务列表
        """
        query = db.query(TrainingTask).filter(TrainingTask.status != "deleted")
        if user_id and not is_superuser:
            query = query.filter(TrainingTask.user_id == user_id)

        tasks = query.order_by(TrainingTask.created_at.desc()).limit(limit).all()

        return [
            {
                "id": t.id,
                "public_task_id": t.public_task_id,
                "task_uuid": t.task_uuid,
                "scene_id": t.scene_id,
                "status": t.status,
                "model_name": t.model_name,
                "epochs": t.epochs,
                "current_epoch": t.current_epoch,
                "progress": t.progress,
                "device": t.device,
                "batch_size": t.batch_size,
                "img_size": t.img_size,
                "optimizer": t.optimizer,
                "lr0": t.lr0,
                "augment_config": t.augment_config,
                "train_config": t.train_config or {},
                "dataset_path": t.dataset_path,
                "dataset_name": os.path.basename(os.path.normpath(t.dataset_path)) if t.dataset_path else None,
                "dataset_size": t.dataset_size,
                "created_at": str(t.created_at),
                "started_at": str(t.started_at) if t.started_at else None,
                "completed_at": str(t.completed_at) if t.completed_at else None,
                "error_message": t.error_message,
            }
            for t in tasks
        ]

    @staticmethod
    def delete_training_task(
        db,
        task_id: int,
        deleted_by_id: int | None = None,
        expected_version: int | None = None,
    ) -> dict:
        """Move an ended training task to the 30-day recycle bin."""
        task = db.query(TrainingTask).filter(TrainingTask.id == task_id).first()
        if not task:
            return {"error": "训练任务不存在"}
        if task.status in {"pending", "running"}:
            return {"error": "运行中的训练任务不能删除，请先停止训练"}

        if task.deletion_status != "active":
            return {"error": "训练任务已在回收站中"}
        if expected_version is not None and task.resource_version != expected_version:
            return {
                "error": "资源已被其他请求修改",
                "code": "resource_changed",
                "current_version": task.resource_version,
            }
        task.deletion_status = "trashed"
        task.deleted_at = datetime.now()
        task.deleted_by_id = deleted_by_id
        task.purge_after = datetime.now() + timedelta(days=30)
        task.resource_version += 1
        db.commit()
        logger.info("训练历史任务已移入回收站: task_id=%d, uuid=%s", task_id, task.task_uuid)
        return {
            "task_id": task_id,
            "public_task_id": task.public_task_id,
            "resource_version": task.resource_version,
            "message": "训练历史任务已移入回收站",
        }

    @staticmethod
    def restore_training_task(db, task_id: int, expected_version: int | None = None) -> dict:
        task = db.query(TrainingTask).filter(TrainingTask.id == task_id).first()
        if not task:
            return {"error": "训练任务不存在"}
        if task.deletion_status != "trashed":
            return {"error": "训练任务不在可恢复状态"}
        if expected_version is not None and task.resource_version != expected_version:
            return {
                "error": "资源已被其他请求修改",
                "code": "resource_changed",
                "current_version": task.resource_version,
            }
        task.deletion_status = "active"
        task.deleted_at = None
        task.deleted_by_id = None
        task.purge_after = None
        task.resource_version += 1
        db.commit()
        return {
            "task_id": task.id,
            "public_task_id": task.public_task_id,
            "resource_version": task.resource_version,
            "message": "训练任务已恢复",
        }

    @staticmethod
    def parse_results_csv(results_csv_path: str) -> list:
        """
        独立解析 results.csv 文件（工具方法，可用于离线分析）

        Args:
            results_csv_path: results.csv 文件路径

        Returns:
            解析后的指标列表
        """
        metrics = []
        if not os.path.exists(results_csv_path):
            return metrics

        with open(results_csv_path, "r", encoding="utf-8") as f:
            rows = [
                {k.strip(): v.strip() for k, v in row.items()}
                for row in csv.DictReader(f)
            ]
            epoch_offset = 1 if rows and min(int(row.get("epoch", 0)) for row in rows) == 0 else 0
            for row in rows:
                metrics.append(
                    {
                        "epoch": int(row.get("epoch", 0)) + epoch_offset,
                        "box_loss": _safe_float(row.get("train/box_loss", "")),
                        "cls_loss": _safe_float(row.get("train/cls_loss", "")),
                        "dfl_loss": _safe_float(row.get("train/dfl_loss", "")),
                        "precision": _safe_float(row.get("metrics/precision(B)", "")),
                        "recall": _safe_float(row.get("metrics/recall(B)", "")),
                        "map50": _safe_float(row.get("metrics/mAP50(B)", "")),
                        "map50_95": _safe_float(row.get("metrics/mAP50-95(B)", "")),
                        "lr": _safe_float(row.get("lr/pg0", "")),
                    }
                )
        return metrics

    @staticmethod
    def validate_model(
        db,
        task_id: int,
        split: str = "val",
        conf: float = 0.001,
        iou: float = 0.6,
    ) -> dict:
        """对已完成训练的模型执行验证集评估"""
        from ultralytics import YOLO
        from app.entity.db_models import ModelVersion, DetectionScene

        task = db.query(TrainingTask).filter(TrainingTask.id == task_id).first()
        if not task:
            return {"error": "训练任务不存在"}

        if task.status != "completed":
            return {"error": f"训练任务状态为 {task.status}，只有已完成的任务才能评估"}

        original_cwd = os.getcwd()
        weights_path = os.path.join(
            original_cwd,
            settings.TRAIN_OUTPUT_DIR,
            f"task_{task.task_uuid}",
            "weights",
            "best.pt",
        )

        if not os.path.exists(weights_path):
            return {"error": f"模型权重不存在: {weights_path}"}

        data_yaml = task.data_yaml
        if not data_yaml or not os.path.exists(data_yaml):
            if task.dataset_path:
                data_yaml = os.path.join(task.dataset_path, "data.yaml")
            if not os.path.exists(data_yaml):
                return {"error": "data.yaml 不存在"}

        logger.info(
            "开始模型评估: task_id=%d, weights=%s, split=%s",
            task_id, weights_path, split,
        )

        try:
            model = YOLO(weights_path)
            results = model.val(
                data=data_yaml,
                split=split,
                conf=conf,
                iou=iou,
                imgsz=task.img_size,
                device="cpu",
                save_json=True,
                plots=True,
                project=os.path.join(
                    original_cwd, settings.TRAIN_OUTPUT_DIR
                ),
                name=f"task_{task.task_uuid}",
                exist_ok=True,
                verbose=False,
            )

            overall = {
                "precision": float(results.box.mp),
                "recall": float(results.box.mr),
                "map50": float(results.box.map50),
                "map50_95": float(results.box.map),
            }

            per_class = {}
            if results.box.ap is not None and len(results.box.ap) > 0:
                for i, ap50 in enumerate(results.box.ap50):
                    class_name = model.names.get(i, f"class_{i}")
                    ap50_95 = results.box.ap[i] if i < len(results.box.ap) else 0.0
                    per_class[class_name] = {
                        "ap50": round(float(ap50), 4),
                        "ap50_95": round(float(ap50_95), 4),
                    }

            # Keep visualisation data as JSON rather than forcing clients to
            # consume server-generated PNG files.  The UI renders the curves
            # with its existing ECharts dependency, so this stays inspectable
            # and works for both local and remote storage.
            def average_curve(curve):
                x_values, y_values = curve[0], curve[1]
                if not len(x_values) or not getattr(y_values, "size", len(y_values)):
                    return {"x": [], "y": []}
                y_mean = y_values.mean(axis=0) if getattr(y_values, "ndim", 1) > 1 else y_values
                # 100 points is ample for a smooth chart and avoids returning
                # four 1000-point arrays for each validation request.
                step = max(1, len(x_values) // 100)
                return {
                    "x": [round(float(value), 4) for value in x_values[::step]],
                    "y": [round(float(value), 4) for value in y_mean[::step]],
                }

            curve_results = results.curves_results
            # Ultralytics 8.3 returns [PR, F1, precision-confidence,
            # recall-confidence].  The first curve already contains recall
            # samples on x and precision samples on y; do not substitute the
            # two confidence curves here, which would render a mislabeled
            # recall-vs-precision chart.
            pr_curve = average_curve(curve_results[0])
            visualization = {
                "confusion_matrix": {
                    "labels": [model.names.get(i, f"class_{i}") for i in range(len(model.names))] + ["background"],
                    "matrix": results.confusion_matrix.matrix.tolist(),
                },
                # Precision/recall share the same confidence samples. Pairing
                # them produces the aggregate PR curve for the frontend.
                "pr_curve": pr_curve,
                "f1_curve": average_curve(curve_results[1]),
            }

            report = {
                "task_id": task_id,
                "task_uuid": task.task_uuid,
                "split": split,
                "overall": overall,
                "per_class": per_class,
                "visualization": visualization,
            }

            # 更新或创建 ModelVersion 记录
            scene = (
                db.query(DetectionScene)
                .filter(DetectionScene.id == task.scene_id)
                .first()
            )

            model_version = (
                db.query(ModelVersion)
                .filter(ModelVersion.training_task_id == task_id)
                .first()
            )

            if not model_version:
                existing_count = (
                    db.query(ModelVersion)
                    .filter(ModelVersion.scene_id == task.scene_id)
                    .count()
                )
                version = f"v{existing_count + 1}.0.0"

                model_version = ModelVersion(
                    scene_id=task.scene_id,
                    training_task_id=task_id,
                    owner_id=task.user_id,
                    version=version,
                    model_name=f"{task.model_name}_{scene.name}_{version}" if scene else f"{task.model_name}_{version}",
                    model_type=task.model_name,
                    model_path=weights_path,
                    map50=overall["map50"],
                    map50_95=overall["map50_95"],
                    precision=overall["precision"],
                    recall=overall["recall"],
                    per_class_ap=per_class,
                    file_size=os.path.getsize(weights_path),
                    description=f"训练任务 {task.task_uuid} 自动产出",
                )
                db.add(model_version)
            else:
                model_version.map50 = overall["map50"]
                model_version.map50_95 = overall["map50_95"]
                model_version.precision = overall["precision"]
                model_version.recall = overall["recall"]
                model_version.per_class_ap = per_class

            db.commit()
            report["model_version_id"] = model_version.id
            report["model_version"] = model_version.version

            logger.info(
                "模型评估完成: task_id=%d, mAP50=%.4f, mAP50-95=%.4f",
                task_id, overall["map50"], overall["map50_95"],
            )

            return report

        except Exception as e:
            logger.error("模型评估异常: task_id=%d, error=%s", task_id, str(e), exc_info=True)
            return {"error": f"评估失败: {str(e)}"}

    @staticmethod
    def export_model(
        db,
        task_id: int,
        version: str = None,
        description: str = None,
        set_default: bool = False,
        upload_minio: bool = True,
    ) -> dict:
        """导出训练好的模型为正式版本"""
        import shutil
        import json
        from app.entity.db_models import ModelVersion, DetectionScene

        task = db.query(TrainingTask).filter(TrainingTask.id == task_id).first()
        if not task:
            return {"error": "训练任务不存在"}

        if task.status != "completed":
            return {"error": f"训练任务状态为 {task.status}，只有已完成的任务才能导出"}

        original_cwd = os.getcwd()
        weights_path = os.path.join(
            original_cwd,
            settings.TRAIN_OUTPUT_DIR,
            f"task_{task.task_uuid}",
            "weights",
            "best.pt",
        )

        if not os.path.exists(weights_path):
            return {"error": f"模型权重不存在: {weights_path}"}

        scene = (
            db.query(DetectionScene)
            .filter(DetectionScene.id == task.scene_id)
            .first()
        )
        if not scene:
            return {"error": "关联场景不存在"}

        # 导出结果的指标必须来自一次成功的验证。若验证失败，不能生成
        # 看似可用但没有可靠评估数据的模型版本或导出目录。
        eval_result = TrainingService.validate_model(db, task_id, split="val")
        if "error" in eval_result:
            return {"error": f"模型导出前评估失败: {eval_result['error']}"}

        overall = eval_result["overall"]
        per_class = eval_result["per_class"]

        if not version:
            existing_count = (
                db.query(ModelVersion)
                .filter(ModelVersion.scene_id == task.scene_id)
                .count()
            )
            version = f"v{existing_count + 1}.0.0"

        export_dir = os.path.join(
            original_cwd,
            "models",
            f"{scene.name}_{version}",
        )
        os.makedirs(export_dir, exist_ok=True)

        exported_weight = os.path.join(export_dir, "best.pt")
        shutil.copy2(weights_path, exported_weight)
        logger.info("模型文件已复制: %s -> %s", weights_path, exported_weight)

        # 复制评估图表
        task_output_dir = os.path.join(
            original_cwd,
            settings.TRAIN_OUTPUT_DIR,
            f"task_{task.task_uuid}",
        )
        eval_plots = [
            "confusion_matrix.png",
            "PR_curve.png",
            "F1_curve.png",
            "results.png",
        ]
        for plot_name in eval_plots:
            src = os.path.join(task_output_dir, plot_name)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(export_dir, plot_name))

        # 保存评估报告 JSON
        report = {
            "version": version,
            "model_name": task.model_name,
            "scene": scene.name,
            "training_task": task.task_uuid,
            "evaluation": {
                "split": "val",
                "overall": overall,
                "per_class": per_class,
            },
            "training_config": {
                "epochs": task.epochs,
                "batch_size": task.batch_size,
                "img_size": task.img_size,
                "optimizer": task.optimizer,
                "lr0": task.lr0,
                "device": task.device,
            },
            "exported_at": datetime.now().isoformat(),
        }
        report_path = os.path.join(export_dir, "eval_report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        # 上传到 MinIO
        minio_url = None
        object_name = None
        if upload_minio:
            try:
                from app.storage.minio_client import MinIOClient
                minio_client = MinIOClient()
                object_name = f"models/{scene.name}/{version}/best.pt"
                minio_url = minio_client.upload_file(object_name, exported_weight)
                logger.info("模型已上传对象存储: object_key=%s", object_name)
            except Exception as e:
                logger.warning("MinIO 上传失败（不影响导出）: %s", str(e))

        # 创建/更新 ModelVersion 记录
        model_version = (
            db.query(ModelVersion)
            .filter(ModelVersion.training_task_id == task_id)
            .first()
        )

        if model_version:
            model_version.version = version
            model_version.model_name = f"{task.model_name}_{scene.name}_{version}"
            model_version.model_type = task.model_name
            model_version.model_path = exported_weight
            model_version.minio_url = minio_url
            model_version.object_key = object_name if upload_minio else None
            model_version.map50 = overall.get("map50")
            model_version.map50_95 = overall.get("map50_95")
            model_version.precision = overall.get("precision")
            model_version.recall = overall.get("recall")
            model_version.per_class_ap = per_class
            model_version.file_size = os.path.getsize(exported_weight)
            model_version.description = description or f"训练任务 {task.task_uuid} 导出"
        else:
            model_version = ModelVersion(
                scene_id=task.scene_id,
                training_task_id=task_id,
                owner_id=task.user_id,
                version=version,
                model_name=f"{task.model_name}_{scene.name}_{version}",
                model_type=task.model_name,
                model_path=exported_weight,
                object_key=object_name if upload_minio else None,
                minio_url=minio_url,
                map50=overall.get("map50"),
                map50_95=overall.get("map50_95"),
                precision=overall.get("precision"),
                recall=overall.get("recall"),
                per_class_ap=per_class,
                file_size=os.path.getsize(exported_weight),
                description=description or f"训练任务 {task.task_uuid} 导出",
            )
            db.add(model_version)

        # 设置默认模型
        if set_default:
            db.query(ModelVersion).filter(
                ModelVersion.scene_id == task.scene_id,
                ModelVersion.id != model_version.id,
            ).update({"is_default": False})
            model_version.is_default = True

        db.commit()
        db.refresh(model_version)

        logger.info(
            "模型导出完成: scene=%s, version=%s, mAP50=%.4f",
            scene.name, version, overall.get("map50", 0),
        )

        return {
            "model_version_id": model_version.id,
            "version": version,
            "model_name": model_version.model_name,
            "model_path": exported_weight,
            "export_dir": export_dir,
            "minio_url": minio_url,
            "file_size": model_version.file_size,
            "evaluation": {
                "map50": overall.get("map50"),
                "map50_95": overall.get("map50_95"),
                "precision": overall.get("precision"),
                "recall": overall.get("recall"),
                "per_class": per_class,
            },
            "is_default": model_version.is_default,
            "message": f"模型已导出为版本 {version}",
        }

    @staticmethod
    def get_model_download_path(db, task_id: int) -> dict:
        """获取训练任务的模型权重文件路径（用于下载）"""
        task = db.query(TrainingTask).filter(TrainingTask.id == task_id).first()
        if not task:
            return {"error": "训练任务不存在"}

        original_cwd = os.getcwd()

        output_root = Path(original_cwd, settings.TRAIN_OUTPUT_DIR).resolve()
        task_root = (output_root / f"task_{task.task_uuid}").resolve()
        if output_root not in task_root.parents:
            return {"error": "模型权重文件不存在"}

        best_path = str(task_root / "weights" / "best.pt")

        if os.path.exists(best_path):
            return {
                "file_path": best_path,
                "filename": f"best_{task.task_uuid}.pt",
                "file_size": os.path.getsize(best_path),
            }

        last_path = str(task_root / "weights" / "last.pt")

        if os.path.exists(last_path):
            return {
                "file_path": last_path,
                "filename": f"last_{task.task_uuid}.pt",
                "file_size": os.path.getsize(last_path),
            }

        return {"error": "模型权重文件不存在"}


# ══════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════


def _safe_float(value) -> float:
    """安全地将字符串转换为浮点数，失败时返回 None"""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


# ══════════════════════════════════════════════════════════════
# 全局单例
# ══════════════════════════════════════════════════════════════

training_service = TrainingService()
