"""
训练相关 API 路由

接口列表：
  - POST   /api/training/start              启动训练任务
  - GET    /api/training/tasks               获取训练任务列表
  - GET    /api/training/status/{task_id}    获取训练状态（含最新指标）
  - GET    /api/training/metrics/{task_id}   获取训练指标历史（所有 epoch）
  - POST   /api/training/stop/{task_id}      停止训练任务
  - GET    /api/training/results/{task_uuid}  获取 results.csv 原始数据
  - POST   /api/training/validate/{task_id}  模型评估
  - POST   /api/training/export/{task_id}    模型导出
  - GET    /api/training/download/{task_id}  下载模型权重
  - POST   /api/training/predict            测试图验证
"""

import base64
import io
import math
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import cv2
import yaml
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.training.dataset_importer import DatasetImportError, import_dataset
from app.config.settings import settings
from app.config.detection import MAX_IMAGE_SIZE
from app.core.logger import get_logger
from app.services.action_confirmation_service import action_confirmation_service
from app.services.operation_log_service import operation_log_service
from app.services.undo_service import undo_service
from app.database.session import get_db
from app.entity.db_models import ModelVersion, TrainingDataset, TrainingTask, User, default_purge_after
from app.storage.minio_client import MinIOClient
from app.entity.schemas import (
    ModelExportRequest,
    ModelValidateRequest,
    TrainingMetricResponse,
    TrainingDatasetMetadataUpdate,
    TrainingTaskCreate,
    TrainingTaskResponse,
)
from app.training.training_service import training_service
from app.services.authorization_service import authorization_service
from app.services.resource_lifecycle_service import resource_lifecycle_service

logger = get_logger(__name__)

BUILTIN_DATASET_PATH = "NEU-DET.v9i.yolov11"
MAX_DATASET_ARCHIVE_BYTES = 500 * 1024 * 1024
MAX_DATASET_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024
ALLOWED_DATASET_SUFFIXES = {
    ".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff",
    ".txt", ".yaml", ".yml", ".xml", ".json",
}


def _is_builtin_dataset(record: TrainingDataset | None) -> bool:
    return bool(record and record.is_builtin)


def _is_builtin_dataset_path(dataset_path: str, record: TrainingDataset | None = None) -> bool:
    # The dataset list exposes the root dataset as ``.``.  Treat that stable
    # relative alias exactly like the shipped dataset name so starting a task
    # does not fail the ownership lookup with RESOURCE_NOT_FOUND.
    return dataset_path in {".", BUILTIN_DATASET_PATH} or _is_builtin_dataset(record)

router = APIRouter(prefix="/api/training", tags=["模型训练"])


def _dataset_root() -> Path:
    project_root = Path(__file__).resolve().parents[3]
    return (project_root / settings.DATASET_BASE_DIR).resolve()


def _safe_dataset_path(dataset_path: str | None) -> Path:
    root = _dataset_root()
    candidate = (root / dataset_path).resolve() if dataset_path else root
    if candidate != root and root not in candidate.parents:
        raise HTTPException(status_code=400, detail="数据集路径无效")
    return candidate


def _dataset_image_count(dataset_path: Path) -> int:
    image_suffixes = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
    return sum(
        1 for item in dataset_path.rglob("*")
        if item.is_file() and item.suffix.lower() in image_suffixes
    )


def _validate_dataset_archive(archive_file: zipfile.ZipFile) -> None:
    """Reject unsafe, oversized or unsupported dataset archives before extraction.

    ZIP producers commonly write the same metadata file more than once (for
    example, Roboflow exports may contain three identical ``data.yaml``
    entries).  Identical entries are harmless and ``extractall`` would simply
    overwrite them, so they are accepted.  A repeated path with different
    bytes is still rejected.  Images with equal bytes at different paths are
    also allowed: real-world datasets (including NEU) can legitimately contain
    duplicate samples under different filenames.
    """
    total_uncompressed = 0
    seen_paths: dict[str, tuple[int, int]] = {}
    image_count = 0
    for member in archive_file.infolist():
        if member.is_dir():
            continue
        normalized = member.filename.replace("\\", "/").strip("/")
        if not normalized:
            raise HTTPException(status_code=400, detail={"code": "DUPLICATE_CONTENT", "message": "数据集压缩包包含重复文件"})
        path_key = normalized.casefold()
        previous = seen_paths.get(path_key)
        if previous is not None:
            if previous != (member.file_size, member.CRC):
                raise HTTPException(status_code=400, detail={"code": "DUPLICATE_CONTENT", "message": "数据集压缩包包含冲突的重复文件"})
            continue
        seen_paths[path_key] = (member.file_size, member.CRC)
        suffix = Path(normalized).suffix.lower()
        if suffix not in ALLOWED_DATASET_SUFFIXES:
            raise HTTPException(status_code=400, detail={"code": "INVALID_FORMAT", "message": f"数据集包含不支持的文件类型: {suffix or '无扩展名'}"})
        total_uncompressed += member.file_size
        if total_uncompressed > MAX_DATASET_EXTRACTED_BYTES:
            raise HTTPException(status_code=413, detail={"code": "DATASET_TOO_LARGE", "message": "数据集解压后不能超过 2 GB"})
        if suffix in {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}:
            image_count += 1
    if image_count == 0:
        raise HTTPException(status_code=400, detail={"code": "INVALID_DATASET", "message": "数据集至少需要一张图片"})


def _validate_dataset_classes(dataset_path: Path) -> None:
    """Validate data.yaml classes and labels under labels/ without changing uploaded files."""
    try:
        config = yaml.safe_load((dataset_path / "data.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_DATASET", "message": "data.yaml 无法解析"}) from exc
    names = config.get("names") if isinstance(config, dict) else None
    if isinstance(names, dict):
        classes = list(names.values())
    elif isinstance(names, list):
        classes = names
    else:
        classes = []
    if not classes or any(not isinstance(name, str) or not name.strip() for name in classes):
        raise HTTPException(status_code=400, detail={"code": "INVALID_DATASET", "message": "data.yaml 必须定义非空 names 类别列表"})
    if config.get("nc") is not None and config["nc"] != len(classes):
        raise HTTPException(status_code=400, detail={"code": "INVALID_DATASET", "message": "data.yaml 的 nc 与 names 类别数量不一致"})
    for label_file in dataset_path.rglob("*.txt"):
        if "labels" not in {part.lower() for part in label_file.parts}:
            continue
        for line_number, line in enumerate(label_file.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            fields = line.split()
            try:
                class_id = int(fields[0])
                coordinates = [float(value) for value in fields[1:]]
            except (ValueError, IndexError) as exc:
                raise HTTPException(status_code=400, detail={"code": "INVALID_DATASET", "message": f"标签格式无效: {label_file.name}:{line_number}"}) from exc
            if len(fields) != 5 or not 0 <= class_id < len(classes):
                raise HTTPException(status_code=400, detail={"code": "INVALID_DATASET", "message": f"标签类别超出 data.yaml 范围: {label_file.name}:{line_number}"})
            if not all(math.isfinite(value) and 0 <= value <= 1 for value in coordinates) or coordinates[2] <= 0 or coordinates[3] <= 0:
                raise HTTPException(status_code=400, detail={"code": "INVALID_DATASET", "message": f"标签坐标必须是 0-1 范围内的有限值: {label_file.name}:{line_number}"})


def _get_dataset_record(db: Session, dataset_path: str, current_user: User) -> TrainingDataset | None:
    record = db.query(TrainingDataset).filter(
        (TrainingDataset.storage_key == dataset_path) | (TrainingDataset.path == dataset_path)
    ).first()
    if record and record.deletion_status != "active":
        raise HTTPException(status_code=404, detail="数据集不存在")
    if record and not authorization_service.can_access_owner(
        db,
        current_user,
        record.owner_id,
        is_builtin=record.is_builtin,
        cross_user_permission="training:dataset:read_all",
    ):
        raise HTTPException(status_code=403, detail="无权访问该数据集")
    if record and record.status == "deleted":
        raise HTTPException(status_code=404, detail={"code": "RESOURCE_NOT_FOUND", "message": "dataset not found"})
    return record


@router.get("/datasets")
async def list_datasets(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    root = _dataset_root()
    root.mkdir(parents=True, exist_ok=True)
    datasets = []
    records = {
        record.path: record
        for record in db.query(TrainingDataset).filter(TrainingDataset.deletion_status == "active").all()
    }
    for directory in sorted(item for item in root.iterdir() if item.is_dir() and item.name != ".trash"):
        record = records.get(directory.name)
        is_builtin = _is_builtin_dataset_path(directory.name, record)
        if record is None and not is_builtin:
            continue
        if record and record.status == "deleted":
            continue
        if record and not authorization_service.can_access_owner(db, current_user, record.owner_id, is_builtin=is_builtin, cross_user_permission="training:dataset:read_all"):
            continue
        datasets.append({
            "name": record.display_name if record else directory.name,
            "display_name": record.display_name if record else directory.name,
            "path": record.storage_key if record else directory.name,
            "storage_key": record.storage_key if record else directory.name,
            "ready": (directory / "data.yaml").is_file(),
            "owner_id": record.owner_id if record else None,
            "is_builtin": is_builtin,
            "description": record.description if record else None,
            "status": record.status if record else "active",
        })
    if (root / "data.yaml").is_file():
        datasets.insert(0, {"name": root.name, "path": ".", "ready": True, "owner_id": None, "is_builtin": True})
    return {"items": datasets}


@router.patch("/datasets/{dataset_path}")
async def update_dataset_metadata(
    dataset_path: str,
    payload: TrainingDatasetMetadataUpdate,
    request: Request,
    confirmation_id: str | None = Header(default=None, alias="X-Confirmation-ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update metadata only; dataset files and their stable path are not renamed."""
    record = _get_dataset_record(db, dataset_path, current_user)
    if _is_builtin_dataset_path(dataset_path, record):
        raise HTTPException(status_code=403, detail={"code": "BUILTIN_RESOURCE", "message": "内置数据集只读"})
    if record is None:
        raise HTTPException(status_code=404, detail={"code": "RESOURCE_NOT_FOUND", "message": "数据集不存在"})
    if record.owner_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "无权编辑该数据集"})
    action_confirmation_service.require_or_prepare(
        db,
        confirmation_uuid=confirmation_id,
        user_id=current_user.id,
        operation="update_dataset_metadata",
        target_type="dataset",
        target_id=record.path,
        impact={"scope": "change dataset display name or description; files remain unchanged", "reversible": True},
        payload={"dataset_path": record.path, "display_name": payload.display_name, "description": payload.description},
        request_id=getattr(request.state, "request_id", None),
    )
    previous_display_name = record.display_name
    previous_description = record.description
    record.display_name = payload.display_name.strip() if payload.display_name else None
    record.description = payload.description.strip() if payload.description else None
    db.commit()
    db.refresh(record)
    undo_id = None
    if (previous_display_name, previous_description) != (record.display_name, record.description):
        undo_id = undo_service.create(db, current_user.id, "rename_dataset", {
            "dataset_path": record.path,
            "previous_display_name": previous_display_name,
            "previous_description": previous_description,
        }).undo_uuid
    operation_log_service.record(
        db,
        user=current_user,
        module="training",
        action="update_dataset_metadata",
        target_type="dataset",
        target_id=record.path,
        description=f"Update dataset metadata {record.path}",
        request=request,
    )
    return {
        "name": record.display_name or record.path,
        "path": record.path,
        "display_name": record.display_name,
        "description": record.description,
        "owner_id": record.owner_id,
        "is_builtin": record.is_builtin,
        "status": record.status,
        "undo_id": undo_id,
    }


@router.post("/datasets/{dataset_path}/archive")
async def archive_dataset(
    dataset_path: str,
    request: Request,
    confirmation_id: str | None = Header(default=None, alias="X-Confirmation-ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = _get_dataset_record(db, dataset_path, current_user)
    if record is None or _is_builtin_dataset_path(dataset_path, record):
        raise HTTPException(status_code=403, detail={"code": "BUILTIN_RESOURCE", "message": "built-in dataset is read-only"})
    if record.owner_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "not allowed to archive this dataset"})
    action_confirmation_service.require_or_prepare(
        db, confirmation_uuid=confirmation_id, user_id=current_user.id,
        operation="archive_dataset", target_type="dataset", target_id=dataset_path,
        impact={"scope": "hide dataset from active training selection", "reversible": True},
        payload={"dataset_path": dataset_path},
        request_id=getattr(request.state, "request_id", None),
    )
    previous_status = record.status
    record.status = "archived" if record.status != "archived" else "active"
    db.commit()
    undo_id = undo_service.create(db, current_user.id, "archive_dataset", {
        "dataset_path": record.path,
        "previous_status": previous_status,
    }).undo_uuid
    operation_log_service.record(
        db, user=current_user, module="training", action="archive_dataset",
        target_type="dataset", target_id=record.path,
        description=f"Archive dataset {record.path}", request=request,
    )
    return {"path": record.path, "status": record.status, "undo_id": undo_id}


@router.post("/datasets/{dataset_path}/reprocess")
async def reprocess_dataset(
    dataset_path: str,
    request: Request,
    confirmation_id: str | None = Header(default=None, alias="X-Confirmation-ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-validate an extracted dataset before it is selected for training."""
    record = _get_dataset_record(db, dataset_path, current_user)
    dataset = _safe_dataset_path(dataset_path)
    if record is None or not dataset.is_dir():
        raise HTTPException(status_code=404, detail={"code": "RESOURCE_NOT_FOUND", "message": "dataset not found"})
    if record.owner_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "not allowed to reprocess this dataset"})
    if not (dataset / "data.yaml").is_file():
        raise HTTPException(status_code=422, detail={"code": "INVALID_DATASET", "message": "data.yaml is missing"})
    _validate_dataset_classes(dataset)
    action_confirmation_service.require_or_prepare(
        db, confirmation_uuid=confirmation_id, user_id=current_user.id,
        operation="reprocess_dataset", target_type="dataset", target_id=record.path,
        impact={"scope": "revalidate dataset and make it selectable for training", "reversible": True},
        payload={"dataset_path": record.path},
        request_id=getattr(getattr(request, "state", None), "request_id", None),
    )
    record.status = "active"
    db.commit()
    operation_log_service.record(
        db, user=current_user, module="training", action="reprocess_dataset",
        target_type="dataset", target_id=record.path,
        description=f"Reprocess dataset {record.path}", request=request,
    )
    return {"path": record.path, "status": record.status, "ready": True}


@router.get("/datasets/{dataset_path}/download")
async def download_dataset(
    dataset_path: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a temporary ZIP download for one dataset directory."""
    root = _dataset_root()
    dataset = _safe_dataset_path(dataset_path)
    if not dataset.is_dir():
        raise HTTPException(status_code=404, detail={"code": "RESOURCE_NOT_FOUND", "message": "数据集不存在"})
    _get_dataset_record(db, dataset_path, current_user)

    archive_dir = Path(tempfile.mkdtemp(prefix="dataset-download-"))
    archive_path = Path(shutil.make_archive(str(archive_dir / dataset.name), "zip", dataset))
    background_tasks.add_task(shutil.rmtree, archive_dir, ignore_errors=True)
    return FileResponse(path=archive_path, media_type="application/zip", filename=f"{dataset.name}.zip", background=background_tasks)


@router.delete("/datasets/{dataset_path}")
async def delete_dataset(
    dataset_path: str,
    request: Request,
    confirmation_id: str | None = Header(default=None, alias="X-Confirmation-ID"),
    expected_version: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Move an unused dataset to the recoverable trash."""
    root = _dataset_root()
    dataset = _safe_dataset_path(dataset_path)
    if dataset == root:
        raise HTTPException(status_code=400, detail="不能删除数据集根目录")
    if not dataset.is_dir():
        raise HTTPException(status_code=404, detail="数据集不存在")
    record = _get_dataset_record(db, dataset_path, current_user)
    if record is None or record.is_builtin:
        raise HTTPException(status_code=403, detail="内置数据集不可删除")
    if record.owner_id != current_user.id and not authorization_service.has_permission(
        db, current_user, "training:dataset:delete_all"
    ):
        raise HTTPException(status_code=403, detail="无权删除该数据集")

    action_confirmation_service.require_or_prepare(
        db, confirmation_uuid=confirmation_id, user_id=current_user.id,
        operation="delete_dataset", target_type="dataset", target_id=dataset_path,
        impact={"scope": "hide dataset and retain files during the undo window", "reversible": True},
        payload={"dataset_path": dataset_path},
        request_id=getattr(request.state, "request_id", None),
    )

    active_paths = {
        Path(task.dataset_path).resolve()
        for task in db.query(TrainingTask).filter(TrainingTask.status.in_(("pending", "running"))).all()
        if task.dataset_path
    }
    if dataset in active_paths:
        raise HTTPException(status_code=409, detail={"code": "RESOURCE_IN_USE", "message": "该数据集正在被训练任务使用，暂不能删除"})

    previous_status = record.status
    record.status = "deleted"
    db.commit()
    undo_id = undo_service.create(db, current_user.id, "delete_dataset", {
        "dataset_path": dataset_path,
        "previous_status": previous_status,
    }).undo_uuid
    operation_log_service.record(
        db, user=current_user, module="training", action="delete_dataset",
        target_type="dataset", target_id=dataset_path,
        description=f"Delete dataset {dataset_path}", request=request,
    )
    return {"path": dataset_path, "deleted": True, "undo_id": undo_id}


@router.post("/datasets/upload")
async def upload_dataset(
    file: UploadFile = File(...),
    dataset_format: str = Form("auto"),
    train_ratio: float = Form(0.8),
    val_ratio: float = Form(0.1),
    test_ratio: float = Form(0.1),
    split_seed: int = Form(42),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=128),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="数据集必须是 ZIP 文件")
    dataset_name = re.sub(r"[^\w.-]+", "_", Path(file.filename).stem, flags=re.UNICODE).strip("._-")[:120]
    if not dataset_name:
        raise HTTPException(status_code=400, detail={"code": "INVALID_FORMAT", "message": "数据集文件名无效"})
    if not isinstance(idempotency_key, str):
        idempotency_key = None
    if idempotency_key:
        existing = db.query(TrainingDataset).filter(
            TrainingDataset.owner_id == current_user.id,
            TrainingDataset.idempotency_key == idempotency_key,
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail={
                "code": "duplicate_request", "storage_key": existing.storage_key,
                "deletion_status": existing.deletion_status,
            })
    storage_key = f"u{current_user.id}_{uuid4().hex}"
    target = _safe_dataset_path(storage_key)
    # Read only one byte beyond the configured limit so an oversized upload
    # cannot allocate an unbounded request-sized buffer before validation.
    archive = await file.read(MAX_DATASET_ARCHIVE_BYTES + 1)
    if len(archive) > MAX_DATASET_ARCHIVE_BYTES:
        raise HTTPException(status_code=413, detail={"code": "DATASET_TOO_LARGE", "message": "数据集压缩包不能超过 500 MB"})
    dataset_root = _dataset_root()
    dataset_root.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=".dataset-upload-", dir=dataset_root))
    extracted = staging_root / "source"
    prepared = staging_root / "prepared"
    extracted.mkdir()
    conversion_report = None
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as archive_file:
            for member in archive_file.infolist():
                member_path = (extracted / member.filename).resolve()
                if extracted not in member_path.parents and member_path != extracted:
                    raise HTTPException(status_code=400, detail={"code": "INVALID_FORMAT", "message": "数据集压缩包包含非法路径"})
            _validate_dataset_archive(archive_file)
            archive_file.extractall(extracted)
        conversion_report = import_dataset(
            source=extracted,
            target=prepared,
            dataset_format=dataset_format,
            split_ratios=(train_ratio, val_ratio, test_ratio),
            seed=split_seed,
        )
        _validate_dataset_classes(prepared)
        prepared.rename(target)
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail={"code": "INVALID_FORMAT", "message": "数据集压缩包无法解析"})
    except DatasetImportError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": exc.message, "details": exc.details},
        ) from exc
    except HTTPException:
        raise
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)
    record = TrainingDataset(path=storage_key, storage_key=storage_key, display_name=dataset_name, owner_id=current_user.id, is_builtin=False, idempotency_key=idempotency_key)
    db.add(record)
    try:
        db.commit()
    except Exception:
        db.rollback()
        shutil.rmtree(target, ignore_errors=True)
        raise
    return {
        "name": dataset_name,
        "display_name": dataset_name,
        "storage_key": storage_key,
        "path": target.name,
        "ready": True,
        "owner_id": current_user.id,
        "is_builtin": False,
        "conversion": conversion_report,
    }


def _resolve_training_task(db: Session, identifier: str | int):
    value = str(identifier).strip()
    task = db.query(TrainingTask).filter(TrainingTask.id == int(value)).first() if value.isdigit() else None
    return task or db.query(TrainingTask).filter(TrainingTask.task_uuid == value).first()


def _check_task_access(db: Session, task_id: str | int, current_user):
    task = _resolve_training_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="训练任务不存在")
    if task.user_id != current_user.id and not authorization_service.has_permission(
        db, current_user, "training:task:read_all"
    ):
        raise HTTPException(status_code=403, detail="无权访问该训练任务")
    if task.status == "deleted":
        raise HTTPException(status_code=404, detail={"code": "RESOURCE_NOT_FOUND", "message": "训练任务不存在"})
    if task.deletion_status != "active":
        raise HTTPException(status_code=404, detail="训练任务不存在")
    return task


def _retry_dataset_path(task: TrainingTask, db: Session, current_user: User) -> tuple[Path, str | None]:
    """Resolve the persisted dataset without trusting a stale or arbitrary path."""
    root = _dataset_root()
    raw_path = Path(task.dataset_path).resolve() if task.dataset_path else root
    if raw_path != root and root not in raw_path.parents:
        raise HTTPException(status_code=409, detail={
            "code": "DATASET_UNAVAILABLE",
            "message": "The dataset used by the previous run is no longer available",
        })

    requested_path = None if raw_path == root else raw_path.relative_to(root).as_posix()
    if requested_path:
        record = _get_dataset_record(db, requested_path, current_user)
        if record and record.status == "archived":
            raise HTTPException(status_code=409, detail={
                "code": "DATASET_ARCHIVED",
                "message": "The dataset used by the previous run is archived",
            })
    if not (raw_path / "data.yaml").is_file():
        raise HTTPException(status_code=409, detail={
            "code": "DATASET_UNAVAILABLE",
            "message": "The dataset used by the previous run is missing data.yaml",
        })
    return raw_path, requested_path


@router.post("/start")
async def start_training(
    request: TrainingTaskCreate,
    http_request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=128),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    启动模型训练任务

    - **scene_id**: 关联的检测场景 ID
    - **model_name**: 基础模型（yolov11n/s/m/l/x）
    - **epochs**: 训练轮数（10~500）
    - **batch_size**: 批次大小（1~64）
    - **device**: 训练设备（cpu / 0 / 1）
    - **optimizer**: 优化器（SGD / Adam / AdamW）
    - **lr0**: 初始学习率
    - **augment_config**: 数据增强配置（JSON）
    """
    if not isinstance(idempotency_key, str):
        idempotency_key = None

    # ── 构造训练配置 ──
    config = {
        "model_name": request.model_name,
        "epochs": request.epochs,
        "img_size": request.img_size,
        "batch_size": request.batch_size,
        "device": request.device,
        "optimizer": request.optimizer,
        "lr0": request.lr0,
        "augment_config": request.augment_config,
        "idempotency_key": idempotency_key,
    }

    # ── 从场景获取数据集路径 ──
    from app.entity.db_models import DetectionScene
    scene = db.query(DetectionScene).filter(DetectionScene.id == request.scene_id).first()
    if not scene:
        raise HTTPException(status_code=404, detail="检测场景不存在")

    # 数据集路径：project_root/datasets/ssdd/
    api_dir = os.path.dirname(os.path.abspath(__file__))
    app_dir = os.path.dirname(api_dir)
    backend_dir = os.path.dirname(app_dir)
    project_root = os.path.dirname(backend_dir)
    requested_dataset = request.dataset_path
    dataset_path = os.path.join(project_root, settings.DATASET_BASE_DIR)
    if requested_dataset:
        dataset_record = _get_dataset_record(db, requested_dataset, current_user)
        if dataset_record and dataset_record.status == "archived":
            raise HTTPException(status_code=409, detail={"code": "DATASET_ARCHIVED", "message": "该数据集已归档，不能用于训练"})
        dataset_path = str(_safe_dataset_path(requested_dataset))
    config["dataset_path"] = dataset_path
    config["dataset_size"] = _dataset_image_count(Path(dataset_path))

    # 检查 data.yaml 是否存在
    data_yaml = os.path.join(dataset_path, "data.yaml")
    if not os.path.exists(data_yaml):
        raise HTTPException(
            status_code=400,
            detail="数据集缺少 data.yaml，请先完成数据集准备",
        )
    config["data_yaml"] = data_yaml

    # ── 启动训练 ──
    try:
        task = training_service.start_training(
            db=db,
            user_id=current_user.id,
            scene_id=request.scene_id,
            config=config,
        )
    except Exception:
        logger.error("启动训练失败 scene_id=%s user_id=%s", request.scene_id, current_user.id)
        raise HTTPException(status_code=500, detail="启动训练失败，请稍后重试")

    logger.info(
        "用户 %s 启动训练任务：scene=%s, model=%s, epochs=%d",
        current_user.username, scene.name, request.model_name, request.epochs,
    )

    operation_log_service.record(
        db,
        user=current_user,
        module="training",
        action="start",
        target_type="training_task",
        target_id=str(task.id),
        description=f"Start training task {task.id}",
        task_id=str(task.id),
        request=http_request,
    )
    return {
        "id": task.id,
        "public_task_id": task.public_task_id,
        "task_uuid": task.task_uuid,
        "status": task.status,
        "model_name": task.model_name,
        "epochs": task.epochs,
        "message": "训练任务已创建，正在后台启动",
    }


@router.get("/tasks")
async def list_training_tasks(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """获取当前用户的训练任务列表"""
    can_read_all = authorization_service.has_permission(db, current_user, "training:task:read_all")
    tasks = training_service.get_task_list(db, user_id=None if can_read_all else current_user.id)
    return {"total": len(tasks), "items": tasks}


@router.delete("/tasks/{task_id}")
async def delete_training_task(
    task_id: str,
    request: Request,
    confirmation_id: str | None = Header(default=None, alias="X-Confirmation-ID"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """隐藏已结束的训练历史；撤销窗口后才清理指标和未发布输出。"""
    task = _check_task_access(db, task_id, current_user)
    action_confirmation_service.require_or_prepare(
        db, confirmation_uuid=confirmation_id, user_id=current_user.id,
        operation="delete_training_task", target_type="training_task", target_id=str(task_id),
        impact={"scope": "hide training history during the undo window; published model versions remain", "reversible": True},
        payload={"task_id": task_id},
        request_id=getattr(request.state, "request_id", None),
    )
    if task.status in {"pending", "running"}:
        raise HTTPException(status_code=400, detail="运行中的训练任务不能删除，请先停止训练")
    previous_status = task.status
    task.status = "deleted"
    db.commit()
    undo_id = undo_service.create(db, current_user.id, "delete_training_task", {
        "task_id": task.id,
        "previous_status": previous_status,
    }).undo_uuid
    operation_log_service.record(
        db,
        user=current_user,
        module="training",
        action="delete",
        target_type="training_task",
        target_id=str(task_id),
        description=f"Delete training task {task_id}",
        task_id=str(task_id),
        request=request,
    )
    return {"task_id": task.id, "message": "训练任务已删除", "undo_id": undo_id}


@router.post("/retry/{task_id}")
async def retry_training_task(
    task_id: str,
    request: Request,
    confirmation_id: str | None = Header(default=None, alias="X-Confirmation-ID"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Retry a failed/cancelled run using its persisted configuration."""
    task = _check_task_access(db, task_id, current_user)
    if task.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=409, detail={
            "code": "TASK_NOT_RETRYABLE",
            "message": "Only failed or cancelled training tasks can be retried",
        })
    action_confirmation_service.require_or_prepare(
        db,
        confirmation_uuid=confirmation_id,
        user_id=current_user.id,
        operation="retry_training",
        target_type="training_task",
        target_id=str(task_id),
        impact={
            "scope": "creates a new training task using the saved configuration and dataset; the previous run is retained",
            "reversible": False,
        },
        payload={"task_id": task_id, "status": task.status},
        request_id=getattr(request.state, "request_id", None),
    )

    dataset_path, requested_dataset = _retry_dataset_path(task, db, current_user)
    config = {
        "model_name": task.model_name,
        "epochs": task.epochs,
        "img_size": task.img_size,
        "batch_size": task.batch_size,
        "device": task.device,
        "optimizer": task.optimizer,
        "lr0": task.lr0,
        "augment_config": task.augment_config,
        "dataset_path": str(dataset_path),
        "dataset_size": _dataset_image_count(dataset_path),
        "data_yaml": str(dataset_path / "data.yaml"),
    }
    try:
        retried = training_service.start_training(
            db=db,
            user_id=current_user.id,
            scene_id=task.scene_id,
            config=config,
        )
    except Exception as exc:
        logger.error("Training retry failed: %s", str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="Training retry failed") from exc

    operation_log_service.record(
        db,
        user=current_user,
        module="training",
        action="retry",
        target_type="training_task",
        target_id=str(retried.id),
        description=f"Retry training task {task.id}",
        task_id=str(retried.id),
        request=request,
    )

    return {
        "id": retried.id,
        "task_uuid": retried.task_uuid,
        "status": retried.status,
        "model_name": retried.model_name,
        "epochs": retried.epochs,
        "source_task_id": task.id,
        "dataset_path": requested_dataset,
    }


@router.post("/tasks/{task_id}/restore")
async def restore_training_task(
    task_id: int,
    expected_version: int | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    task = db.query(TrainingTask).filter(TrainingTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="训练任务不存在")
    if task.user_id != current_user.id and not authorization_service.has_permission(
        db, current_user, "training:task:delete_all"
    ):
        raise HTTPException(status_code=403, detail="无权恢复该训练任务")
    result = training_service.restore_training_task(db, task_id, expected_version)
    if "error" in result:
        status_code = 409 if result.get("code") == "resource_changed" else 400
        raise HTTPException(status_code=status_code, detail=result)
    return result


@router.delete("/tasks/{task_id}/purge")
async def purge_training_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    task = db.query(TrainingTask).filter(TrainingTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="训练任务不存在")
    if task.user_id != current_user.id and not authorization_service.has_permission(
        db, current_user, "training:task:delete_all"
    ):
        raise HTTPException(status_code=403, detail="无权彻底删除该训练任务")
    job = resource_lifecycle_service.purge_training_task(db, task)
    return {"message": "训练任务已彻底删除", "cleanup_job_id": job.id, "status": job.status}


@router.get("/status/{task_id}")
async def get_training_status(
    task_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    获取训练任务状态

    返回任务基本信息、当前进度和最新 epoch 指标
    前端可轮询此接口实现实时监控
    """
    _check_task_access(db, task_id, current_user)
    status = training_service.get_training_status(db, task_id)
    if "error" in status:
        raise HTTPException(status_code=404, detail=status["error"])
    return status


@router.get("/metrics/{task_id}")
async def get_training_metrics(
    task_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    获取训练任务的所有 epoch 指标

    用于绘制完整的训练曲线（loss、mAP、precision、recall）
    """
    _check_task_access(db, task_id, current_user)
    metrics = training_service.get_training_metrics(db, task_id)
    return {"task_id": task_id, "total": len(metrics), "metrics": metrics}


@router.post("/stop/{task_id}")
async def stop_training(
    task_id: str,
    request: Request,
    confirmation_id: str | None = Header(default=None, alias="X-Confirmation-ID"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """停止正在运行的训练任务"""
    task = _check_task_access(db, task_id, current_user)
    action_confirmation_service.require_or_prepare(
        db, confirmation_uuid=confirmation_id, user_id=current_user.id,
        operation="stop_training", target_type="training_task", target_id=str(task_id),
        impact={"scope": "stop active training process; partial outputs may remain", "reversible": False},
        payload={"task_id": task_id},
        request_id=getattr(request.state, "request_id", None),
    )
    result = training_service.stop_training(db, task.id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    operation_log_service.record(
        db,
        user=current_user,
        module="training",
        action="stop",
        target_type="training_task",
        target_id=str(task_id),
        description=f"Stop training task {task_id}",
        task_id=str(task_id),
        request=request,
    )
    return result


@router.get("/results/{task_uuid}")
async def get_results_csv(
    task_uuid: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    获取 Ultralytics 生成的原始 results.csv 文件

    可用于离线分析或导出到其他工具
    """
    task = db.query(TrainingTask).filter(TrainingTask.task_uuid == task_uuid).first()
    if not task:
        raise HTTPException(status_code=404, detail="训练任务不存在")
    _check_task_access(db, task.id, current_user)
    output_root = Path(os.getcwd(), settings.TRAIN_OUTPUT_DIR).resolve()
    task_root = (output_root / f"task_{task_uuid}").resolve()
    if output_root not in task_root.parents:
        raise HTTPException(status_code=404, detail="results.csv 文件不存在")
    results_path = (task_root / "results.csv").resolve()
    if output_root not in results_path.parents or not results_path.is_file():
        raise HTTPException(status_code=404, detail="results.csv 文件不存在")

    return FileResponse(
        path=results_path,
        media_type="text/csv",
        filename=f"training_results_{task_uuid}.csv",
    )


@router.post("/validate/{task_id}")
async def validate_training_model(
    task_id: int,
    request: ModelValidateRequest = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    对已完成训练的模型执行评估

    - 在验证集或测试集上运行 model.val()
    - 返回 mAP、Precision、Recall 等指标
    - 返回每类 AP 分析
    - 自动创建/更新 ModelVersion 记录
    """
    _check_task_access(db, task_id, current_user)
    if request is None:
        request = ModelValidateRequest()

    result = training_service.validate_model(
        db=db, task_id=task_id,
        split=request.split, conf=request.conf, iou=request.iou,
    )

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    logger.info(
        "用户 %s 评估模型: task_id=%d, mAP50=%.4f",
        current_user.username, task_id,
        result.get("overall", {}).get("map50", 0),
    )
    return result


@router.post("/export/{task_id}")
async def export_training_model(
    task_id: int,
    request: ModelExportRequest = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    导出训练好的模型为正式版本

    - 复制 best.pt 到 models/ 目录
    - 运行评估获取最终指标
    - 保存评估报告 JSON
    - 创建 ModelVersion 记录
    - 可选上传到 MinIO
    """
    _check_task_access(db, task_id, current_user)
    if request is None:
        request = ModelExportRequest()

    result = training_service.export_model(
        db=db, task_id=task_id,
        version=request.version, description=request.description,
        set_default=request.set_default, upload_minio=request.upload_minio,
    )

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    logger.info(
        "用户 %s 导出模型: task_id=%d, version=%s",
        current_user.username, task_id, result.get("version"),
    )
    # Keep internal filesystem and object-store locations server-side.
    return {
        key: value
        for key, value in result.items()
        if key not in {"model_path", "export_dir", "minio_url", "object_key"}
    }


@router.get("/download/{task_id}")
async def download_training_model(
    task_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """下载训练好的模型权重文件（best.pt）"""
    task = _check_task_access(db, task_id, current_user)
    stored_model = (
        db.query(ModelVersion)
        .filter(ModelVersion.training_task_id == task_id, ModelVersion.object_key.isnot(None))
        .order_by(ModelVersion.created_at.desc())
        .first()
    )
    if stored_model and stored_model.object_key:
        url = MinIOClient().get_presigned_url(stored_model.object_key)
        if url:
            logger.info(
                "用户 %s 下载训练模型: task_id=%d, object_key=%s",
                current_user.username, task_id, stored_model.object_key,
            )
            return RedirectResponse(url=url, status_code=307)
    result = training_service.get_model_download_path(db, task_id)

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    logger.info(
        "用户 %s 下载模型: task_id=%d, file=%s",
        current_user.username, task_id, result["filename"],
    )
    return FileResponse(
        path=result["file_path"],
        media_type="application/octet-stream",
        filename=result["filename"],
    )


@router.get("/report/{task_id}")
async def download_training_report(
    task_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Export persisted training metrics, evaluation and model lineage as Markdown."""
    _check_task_access(db, task_id, current_user)
    report = training_service.build_training_report(db, task_id)
    if "error" in report:
        raise HTTPException(status_code=404, detail=report["error"])
    return PlainTextResponse(
        report["content"], media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{report["filename"]}"'},
    )


@router.post("/predict")
async def predict_training_image(
    file: UploadFile = File(..., description="测试图片"),
    task_id: int = Form(..., description="训练任务 ID"),
    conf: float = Form(0.25, description="置信度阈值"),
    iou: float = Form(0.45, description="NMS IoU 阈值"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    上传测试图片，使用训练好的模型进行预测

    - 使用 best.pt 进行推理
    - 返回标注图 (base64) + 检测结果列表
    """
    from ultralytics import YOLO

    allowed_types = {"image/jpeg", "image/png", "image/bmp", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file.content_type}",
        )

    _check_task_access(db, task_id, current_user)
    task = db.query(TrainingTask).filter(TrainingTask.id == task_id).first()
    if task.status != "completed":
        raise HTTPException(status_code=400, detail="训练任务未完成")

    output_root = Path(os.getcwd(), settings.TRAIN_OUTPUT_DIR).resolve()
    task_root = (output_root / f"task_{task.task_uuid}").resolve()
    weights_path = (task_root / "weights" / "best.pt").resolve()
    if output_root not in task_root.parents or output_root not in weights_path.parents:
        raise HTTPException(status_code=404, detail="模型权重不存在")
    if not os.path.exists(weights_path):
        raise HTTPException(status_code=404, detail="模型权重不存在")

    with tempfile.NamedTemporaryFile(
        suffix=os.path.splitext(file.filename)[1] or ".jpg", delete=False,
    ) as tmp:
        content = await file.read()
        if len(content) > MAX_IMAGE_SIZE:
            raise HTTPException(status_code=413, detail="图片大小不能超过限制")
        tmp.write(content)
        tmp_path = tmp.name

    try:
        model = YOLO(weights_path)
        results = model.predict(
            source=tmp_path, conf=conf, iou=iou,
            imgsz=task.img_size, device="cpu", save=False, verbose=False,
        )

        r = results[0]
        detections = []
        if r.boxes is not None and len(r.boxes) > 0:
            for box in r.boxes:
                cls_id = int(box.cls[0])
                cls_name = model.names.get(cls_id, f"class_{cls_id}")
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                detections.append({
                    "class_name": cls_name,
                    "class_id": cls_id,
                    "confidence": round(float(box.conf[0]), 4),
                    "bbox": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                })

        annotated_img = r.plot()
        import cv2

        _, buf = cv2.imencode(".jpg", annotated_img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        annotated_b64 = base64.b64encode(buf).decode("utf-8")

        class_counts = {}
        for d in detections:
            class_counts[d["class_name"]] = class_counts.get(d["class_name"], 0) + 1

        return {
            "task_id": task_id,
            "task_uuid": task.task_uuid,
            "filename": file.filename,
            "total_objects": len(detections),
            "detections": detections,
            "class_counts": class_counts,
            "annotated_image": annotated_b64,
            "inference_time": round(float(r.speed.get("inference", 0)), 2),
        }
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@router.post("/datasets/{dataset_path}/restore")
async def restore_dataset(
    dataset_path: str,
    expected_version: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = db.query(TrainingDataset).filter(
        (TrainingDataset.storage_key == dataset_path) | (TrainingDataset.path == dataset_path)
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="数据集不存在")
    if record.owner_id != current_user.id and not authorization_service.has_permission(
        db, current_user, "training:dataset:delete_all"
    ):
        raise HTTPException(status_code=403, detail="无权恢复该数据集")
    if record.deletion_status != "trashed":
        raise HTTPException(status_code=409, detail="该数据集不在可恢复状态")
    if expected_version is not None and record.resource_version != expected_version:
        raise HTTPException(status_code=409, detail={
            "code": "resource_changed",
            "current_version": record.resource_version,
        })
    root = _dataset_root()
    source = root / ".trash" / record.storage_key
    target = root / record.storage_key
    if not source.is_dir():
        raise HTTPException(status_code=409, detail="回收站文件缺失，无法恢复")
    if target.exists():
        raise HTTPException(status_code=409, detail="目标存储位置已被占用")
    try:
        shutil.move(str(source), str(target))
        record.deletion_status = "active"
        record.deleted_at = None
        record.deleted_by_id = None
        record.purge_after = None
        record.cleanup_error = None
        record.resource_version += 1
        db.commit()
    except Exception:
        db.rollback()
        if target.is_dir() and not source.exists():
            shutil.move(str(target), str(source))
        raise
    return {
        "path": record.storage_key,
        "display_name": record.display_name,
        "resource_version": record.resource_version,
        "restored": True,
    }


@router.delete("/datasets/{dataset_path}/purge")
async def purge_dataset(
    dataset_path: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = db.query(TrainingDataset).filter(
        (TrainingDataset.storage_key == dataset_path) | (TrainingDataset.path == dataset_path)
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="数据集不存在")
    if record.owner_id != current_user.id and not authorization_service.has_permission(
        db, current_user, "training:dataset:delete_all"
    ):
        raise HTTPException(status_code=403, detail="无权彻底删除该数据集")
    job = resource_lifecycle_service.purge_dataset(db, record, _dataset_root())
    return {"message": "数据集已彻底删除", "cleanup_job_id": job.id, "status": job.status}



@router.post("/datasets/{dataset_path}/trash")
async def trash_delete_dataset(
    dataset_path: str,
    expected_version: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Move an unused dataset to the recoverable trash."""
    root = _dataset_root()
    dataset = _safe_dataset_path(dataset_path)
    if dataset == root:
        raise HTTPException(status_code=400, detail="不能删除数据集根目录")
    if not dataset.is_dir():
        raise HTTPException(status_code=404, detail="数据集不存在")
    record = _get_dataset_record(db, dataset_path, current_user)
    if record is None or record.is_builtin:
        raise HTTPException(status_code=403, detail="内置数据集不可删除")
    if record.owner_id != current_user.id and not authorization_service.has_permission(
        db, current_user, "training:dataset:delete_all"
    ):
        raise HTTPException(status_code=403, detail="无权删除该数据集")

    active_paths = {
        Path(task.dataset_path).resolve()
        for task in db.query(TrainingTask).filter(TrainingTask.status.in_(("pending", "running"))).all()
        if task.dataset_path
    }
    if dataset in active_paths:
        raise HTTPException(status_code=409, detail={"code": "RESOURCE_IN_USE", "message": "该数据集正在被训练任务使用，暂不能删除"})

    if expected_version is not None and record.resource_version != expected_version:
        raise HTTPException(status_code=409, detail={
            "code": "resource_changed",
            "current_version": record.resource_version,
        })
    trash_root = root / ".trash"
    trash_root.mkdir(parents=True, exist_ok=True)
    trash_target = trash_root / record.storage_key
    if trash_target.exists():
        raise HTTPException(status_code=409, detail="回收站中已存在同一资源")
    try:
        shutil.move(str(dataset), str(trash_target))
        record.deletion_status = "trashed"
        record.deleted_at = datetime.now()
        record.deleted_by_id = current_user.id
        record.purge_after = default_purge_after()
        record.resource_version += 1
        db.commit()
    except Exception:
        db.rollback()
        if trash_target.is_dir() and not dataset.exists():
            shutil.move(str(trash_target), str(dataset))
        raise
    return {
        "path": record.storage_key,
        "display_name": record.display_name,
        "deleted": True,
        "resource_version": record.resource_version,
        "purge_after": record.purge_after,
    }




@router.post("/tasks/{task_id}/trash")
async def trash_delete_training_task(
    task_id: int,
    expected_version: int | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """删除已结束的训练历史及其指标，保留已发布的模型版本。"""
    _check_task_access(db, task_id, current_user)
    result = training_service.delete_training_task(
        db, task_id, deleted_by_id=current_user.id, expected_version=expected_version
    )
    if "error" in result:
        status_code = 409 if result.get("code") == "resource_changed" else 400
        raise HTTPException(status_code=status_code, detail=result)
    return result
