"""
检测场景 API 路由
- GET  /api/scenes            场景列表
- GET  /api/scenes/{scene_id} 场景详情
- POST /api/scenes            创建场景（管理员）
- POST /api/scenes/{scene_id}/default-model  切换该场景的默认模型（已登录用户）
"""
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database.session import get_db
from app.entity.db_models import ModelVersion, User
from app.entity.schemas import SceneCreate, SceneResponse, ModelVersionBrief, ModelVersionResponse
from app.services.operation_log_service import operation_log_service
from app.services.scene_service import scene_service
from app.services.action_confirmation_service import action_confirmation_service
from app.storage.minio_client import MinIOClient
from app.services.undo_service import undo_service
from app.services.authorization_service import authorization_service
from app.services.resource_lifecycle_service import resource_lifecycle_service

router = APIRouter(prefix="/api/scenes", tags=["检测场景"])
MAX_MODEL_UPLOAD_BYTES = 1024 * 1024 * 1024
MODEL_UNDO_DIR = Path(tempfile.gettempdir()) / "ssdd-model-undo"


def _require_permission(db: Session, current_user: User, code: str):
    authorization_service.require_permission(db, current_user, code)


def _scene_to_response(db: Session, scene) -> SceneResponse:
    default_model = scene_service.get_default_model(db, scene.id)
    data = SceneResponse.model_validate(scene)
    data.default_model = ModelVersionBrief.model_validate(default_model) if default_model else None
    return data


def _model_to_response(model) -> ModelVersionResponse:
    data = ModelVersionResponse.model_validate(model)
    data.model_path = Path(model.model_path).name if model.model_path else ""
    data.minio_url = None
    data.object_key = None
    return data


@router.get("", response_model=list[SceneResponse])
def list_scenes(
    category: str | None = None,
    db: Session = Depends(get_db),
):
    """场景列表（登录与未登录都可查看，前端选择检测场景时用）"""
    scenes = scene_service.list_scenes(db, category=category)
    return [_scene_to_response(db, s) for s in scenes]


@router.get("/{scene_id}", response_model=SceneResponse)
def get_scene(scene_id: int, db: Session = Depends(get_db)):
    scene = scene_service.get_scene(db, scene_id)
    return _scene_to_response(db, scene)


@router.get("/{scene_id}/models", response_model=list[ModelVersionResponse])
def list_scene_models(
    scene_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List every non-deleted model version that can be inspected or selected."""
    return [_model_to_response(model) for model in scene_service.list_model_versions(
        db, scene_id, current_user.id, current_user.is_superuser,
    )]


@router.post("/{scene_id}/models/upload", response_model=ModelVersionResponse, status_code=201)
async def upload_model_version(
    scene_id: int,
    file: UploadFile = File(...),
    version: str = Form(...),
    model_name: str = Form(...),
    model_type: str = Form("yolo11n"),
    description: str | None = Form(None),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # PyTorch checkpoints may execute Python code when loaded. Only trusted
    # model administrators may introduce executable model artifacts.
    _require_permission(db, current_user, "model:manage")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".pt":
        raise HTTPException(status_code=400, detail="仅支持上传 .pt 模型文件")
    project_root = Path(__file__).resolve().parents[3]
    target_dir = project_root / "models" / "users" / str(current_user.id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{uuid4().hex}{suffix}"
    object_key = f"models/users/{current_user.id}/{uuid4().hex}.pt"
    try:
        size = 0
        with target.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_MODEL_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="model file exceeds 1 GB")
                output.write(chunk)
        minio_url = MinIOClient().upload_file(object_key, str(target))
        model = scene_service.create_uploaded_model(
            db, scene_id, current_user.id, version.strip(), model_name.strip(), model_type.strip(),
            str(target.relative_to(project_root)), size, description, object_key, minio_url,
        )
        operation_log_service.record(
            db, user=current_user, module="scenes", action="upload_model",
            target_type="model", target_id=str(model.id),
            description=f"Upload model {model.id}", request=request,
        )
        return _model_to_response(model)
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    except Exception:
        target.unlink(missing_ok=True)
        try:
            MinIOClient().delete_file(object_key)
        except Exception:
            pass
        raise


@router.patch("/{scene_id}/models/{model_version_id}", response_model=ModelVersionResponse)
def update_model_version(
    scene_id: int,
    model_version_id: int,
    http_request: Request,
    version: str | None = Form(None),
    model_name: str | None = Form(None),
    description: str | None = Form(None),
    confirmation_id: str | None = Header(default=None, alias="X-Confirmation-ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    previous = scene_service.get_model_version(
        db, scene_id, model_version_id, current_user.id, current_user.is_superuser,
    )
    action_confirmation_service.require_or_prepare(
        db,
        confirmation_uuid=confirmation_id,
        user_id=current_user.id,
        operation="update_model_version",
        target_type="model",
        target_id=str(model_version_id),
        impact={"scope": "change model name, version, or description", "reversible": True},
        payload={"scene_id": scene_id, "model_version_id": model_version_id, "version": version, "model_name": model_name, "description": description},
        request_id=getattr(http_request.state, "request_id", None),
    )
    model = scene_service.update_model_version(
        db, scene_id, model_version_id, current_user.id, current_user.is_superuser,
        description, version, model_name,
    )
    data = _model_to_response(model)
    if (previous.model_name, previous.version) != (model.model_name, model.version):
        data.undo_id = undo_service.create(db, current_user.id, "rename_model", {
            "scene_id": scene_id,
            "model_version_id": model_version_id,
            "previous_model_name": previous.model_name,
            "previous_version": previous.version,
        }).undo_uuid
    operation_log_service.record(
        db,
        user=current_user,
        module="training",
        action="update_model_version",
        target_type="model",
        target_id=str(model_version_id),
        description=f"Update model version {model_version_id}",
        request=http_request,
    )
    return data


@router.post("/{scene_id}/models/{model_version_id}/trash", response_model=ModelVersionResponse)
def delete_scene_model(
    scene_id: int,
    model_version_id: int,
    http_request: Request,
    expected_version: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    can_manage_all = authorization_service.has_permission(db, current_user, "model:manage_all")
    model = scene_service.delete_model_version(
        db, scene_id, model_version_id, current_user.id, can_manage_all, expected_version, cleanup_files=False
    )
    operation_log_service.record(
        db, user=current_user, module="training", action="trash_model",
        target_type="model", target_id=str(model_version_id),
        description=f"模型 {model_version_id} 移入回收站",
        request=http_request,
    )
    return model


@router.post("/{scene_id}/models/{model_version_id}/restore", response_model=ModelVersionResponse)
def restore_scene_model(
    scene_id: int,
    model_version_id: int,
    http_request: Request,
    expected_version: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    can_manage_all = authorization_service.has_permission(db, current_user, "model:manage_all")
    model = scene_service.restore_model_version(
        db, scene_id, model_version_id, current_user.id, can_manage_all, expected_version
    )
    operation_log_service.record(
        db, user=current_user, module="training", action="restore_model",
        target_type="model", target_id=str(model_version_id),
        description=f"模型 {model_version_id} 从回收站恢复",
        request=http_request,
    )
    return model


@router.delete("/{scene_id}/models/{model_version_id}/purge")
def purge_scene_model(
    scene_id: int,
    model_version_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    model = db.query(ModelVersion).filter(
        ModelVersion.id == model_version_id,
        ModelVersion.scene_id == scene_id,
    ).first()
    if not model:
        raise HTTPException(status_code=404, detail="模型版本不存在")
    can_manage_all = authorization_service.has_permission(db, current_user, "model:manage_all")
    if model.owner_id != current_user.id and not can_manage_all:
        raise HTTPException(status_code=403, detail="无权彻底删除该模型")
    job = resource_lifecycle_service.purge_model_version(db, model)
    return {"message": "模型已彻底删除", "cleanup_job_id": job.id, "status": job.status}


@router.post("", response_model=SceneResponse, status_code=201)
def create_scene(
    payload: SceneCreate,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建检测场景，需要管理员权限"""
    _require_permission(db, current_user, "scene:manage")
    scene = scene_service.create_scene(
        db,
        name=payload.name,
        display_name=payload.display_name,
        category=payload.category,
        class_names=payload.class_names,
        description=payload.description,
        class_names_cn=payload.class_names_cn,
        created_by=current_user.id,
    )
    operation_log_service.record(
        db, user=current_user, module="detection", action="create_scene",
        target_type="scene", target_id=str(scene.id),
        description=f"创建检测场景：{scene.name}", request=http_request,
    )
    return _scene_to_response(db, scene)


@router.post("/{scene_id}/default-model")
def set_default_model(
    scene_id: int,
    model_version_id: int,
    http_request: Request,
    expected_version: int | None = None,
    confirmation_id: str | None = Header(default=None, alias="X-Confirmation-ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """切换当前用户可访问的场景模型版本。"""
    action_confirmation_service.require_or_prepare(
        db, confirmation_uuid=confirmation_id, user_id=current_user.id,
        operation="set_default_model", target_type="model", target_id=str(model_version_id),
        impact={"scope": f"scene {scene_id} default model selection", "reversible": True},
        payload={"scene_id": scene_id, "model_version_id": model_version_id},
        request_id=getattr(http_request.state, "request_id", None),
    )
    _require_permission(db, current_user, "model:set_default")
    can_manage_all = authorization_service.has_permission(db, current_user, "model:manage_all")
    previous = scene_service.get_default_model(db, scene_id)
    model = scene_service.set_default_model(
        db,
        scene_id,
        model_version_id,
        user_id=current_user.id,
        is_superuser=can_manage_all,
        expected_version=expected_version,
    )
    operation_log_service.record(
        db, user=current_user, module="training", action="set_default_model",
        target_type="model", target_id=str(model_version_id),
        description=f"场景 {scene_id} 默认模型切换为版本 {model_version_id}",
        request=http_request,
    )
    data = ModelVersionBrief.model_validate(model).model_dump()
    data["undo_id"] = undo_service.create(db, current_user.id, "set_default_model", {
        "scene_id": scene_id,
        "previous_model_id": previous.id if previous else model_version_id,
    }).undo_uuid
    return data


@router.delete("/{scene_id}/models/{model_version_id}")
def delete_model_version(
    scene_id: int,
    model_version_id: int,
    confirmation_id: str | None = Header(default=None, alias="X-Confirmation-ID"),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    model = scene_service.get_model_version(
        db, scene_id, model_version_id, current_user.id, current_user.is_superuser
    )
    project_root = Path(__file__).resolve().parents[3]
    model_path = Path(model.model_path)
    if not model_path.is_absolute():
        model_path = project_root / model_path
    model_path = model_path.resolve()
    if project_root not in model_path.parents:
        raise HTTPException(status_code=404, detail="模型文件不存在")
    reversible = model_path.is_file()
    action_confirmation_service.require_or_prepare(
        db, confirmation_uuid=confirmation_id, user_id=current_user.id,
        operation="delete_model", target_type="model", target_id=str(model_version_id),
        impact={"scope": "soft-delete model and clean stored model files", "reversible": reversible},
        payload={"scene_id": scene_id, "model_version_id": model_version_id},
        request_id=getattr(getattr(request, "state", None), "request_id", None),
    )
    backup_path = None
    if reversible:
        MODEL_UNDO_DIR.mkdir(parents=True, exist_ok=True)
        backup_path = MODEL_UNDO_DIR / f"{uuid4().hex}{model_path.suffix or '.pt'}"
        shutil.copy2(model_path, backup_path)
    model = scene_service.delete_model_version(
        db, scene_id, model_version_id, current_user.id, current_user.is_superuser
    )
    undo_id = None
    if backup_path:
        undo_id = undo_service.create(db, current_user.id, "delete_model", {
            "scene_id": scene_id,
            "model_version_id": model_version_id,
            "previous_status": "active",
            "model_path": str(model_path),
            "backup_path": str(backup_path),
        }).undo_uuid
    operation_log_service.record(
        db, user=current_user, module="scenes", action="delete_model",
        target_type="model", target_id=str(model_version_id),
        description=f"Delete model {model_version_id}", request=request,
    )
    return {"id": model.id, "status": model.status, "undo_id": undo_id}


@router.post("/{scene_id}/models/{model_version_id}/archive", response_model=ModelVersionResponse)
def archive_model_version(
    scene_id: int,
    model_version_id: int,
    confirmation_id: str | None = Header(default=None, alias="X-Confirmation-ID"),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    action_confirmation_service.require_or_prepare(
        db, confirmation_uuid=confirmation_id, user_id=current_user.id,
        operation="archive_model", target_type="model", target_id=str(model_version_id),
        impact={"scope": "hide model from active model selection", "reversible": True},
        payload={"scene_id": scene_id, "model_version_id": model_version_id},
        request_id=getattr(getattr(request, "state", None), "request_id", None),
    )
    previous = scene_service.get_model_version(
        db, scene_id, model_version_id, current_user.id, current_user.is_superuser,
    )
    model = scene_service.archive_model_version(
        db, scene_id, model_version_id, current_user.id, current_user.is_superuser,
    )
    data = _model_to_response(model)
    data.undo_id = undo_service.create(db, current_user.id, "archive_model", {
        "scene_id": scene_id,
        "model_version_id": model_version_id,
        "previous_status": previous.status,
    }).undo_uuid
    operation_log_service.record(
        db, user=current_user, module="scenes", action="archive_model",
        target_type="model", target_id=str(model_version_id),
        description=f"Archive model {model_version_id}", request=request,
    )
    return data


@router.post("/{scene_id}/models/{model_version_id}/retry-cleanup", response_model=ModelVersionResponse)
def retry_model_cleanup(
    scene_id: int,
    model_version_id: int,
    confirmation_id: str | None = Header(default=None, alias="X-Confirmation-ID"),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    action_confirmation_service.require_or_prepare(
        db, confirmation_uuid=confirmation_id, user_id=current_user.id,
        operation="retry_model_cleanup", target_type="model", target_id=str(model_version_id),
        impact={"scope": "retry deletion of model object-store files", "reversible": False},
        payload={"scene_id": scene_id, "model_version_id": model_version_id},
        request_id=getattr(getattr(request, "state", None), "request_id", None),
    )
    model = scene_service.retry_model_cleanup(
        db, scene_id, model_version_id, current_user.id, current_user.is_superuser,
    )
    operation_log_service.record(
        db, user=current_user, module="scenes", action="retry_model_cleanup",
        target_type="model", target_id=str(model_version_id),
        description=f"Retry model cleanup {model_version_id}", request=request,
    )
    return _model_to_response(model)


@router.get("/{scene_id}/models/{model_version_id}/download")
def download_model_version(
    scene_id: int,
    model_version_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    model = scene_service.get_model_version(
        db, scene_id, model_version_id, current_user.id, current_user.is_superuser
    )
    project_root = Path(__file__).resolve().parents[3]
    model_path = Path(model.model_path)
    if not model_path.is_absolute():
        model_path = project_root / model_path
    model_path = model_path.resolve()
    if project_root not in model_path.parents:
        raise HTTPException(status_code=404, detail="模型文件不存在")
    if model_path.is_file():
        return FileResponse(path=model_path, media_type="application/octet-stream", filename=model_path.name)
    if model.object_key:
        return RedirectResponse(url=MinIOClient().get_presigned_url(model.object_key))
    raise HTTPException(status_code=404, detail="模型文件不存在")
