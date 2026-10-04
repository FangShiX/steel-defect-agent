import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database.session import get_db
from app.entity.db_models import ChatSession, DetectionTask, KnowledgeDocument, ModelVersion, TrainingDataset, TrainingTask, User
from app.services.chat_service import chat_service
from app.services.scene_service import scene_service
from app.services.undo_service import undo_service

router = APIRouter(prefix="/api/undo", tags=["undo"])


@router.post("/{undo_uuid}")
def undo(undo_uuid: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    action = undo_service.consume(db, current_user.id, undo_uuid)
    payload = action.payload
    if action.operation == "rename_chat":
        chat_service.rename_session(db, payload["session_uuid"], current_user.id, payload["previous_title"], current_user.is_superuser)
    elif action.operation == "archive_chat":
        session = db.query(ChatSession).filter(ChatSession.session_uuid == payload["session_uuid"], ChatSession.user_id == current_user.id).first()
        if session is None:
            raise HTTPException(status_code=404, detail={"code": "RESOURCE_NOT_FOUND", "message": "chat session not found"})
        session.status = payload["previous_status"]
        db.commit()
    elif action.operation == "delete_chat_session":
        session = db.query(ChatSession).filter(
            ChatSession.session_uuid == payload["session_uuid"],
            ChatSession.user_id == current_user.id,
        ).first()
        if session is None:
            raise HTTPException(status_code=404, detail={"code": "RESOURCE_NOT_FOUND", "message": "chat session not found"})
        if session.status != "deleted":
            raise HTTPException(status_code=409, detail={"code": "UNDO_CONFLICT", "message": "chat session is no longer deleted"})
        session.status = payload.get("previous_status", "active")
        db.commit()
    elif action.operation == "delete_training_task":
        task = db.query(TrainingTask).filter(
            TrainingTask.id == payload["task_id"], TrainingTask.user_id == current_user.id,
        ).first()
        if task is None:
            raise HTTPException(status_code=404, detail={"code": "RESOURCE_NOT_FOUND", "message": "training task not found"})
        if task.status != "deleted":
            raise HTTPException(status_code=409, detail={"code": "UNDO_CONFLICT", "message": "training task is no longer deleted"})
        task.status = payload.get("previous_status", "completed")
        db.commit()
    elif action.operation == "delete_detection_task":
        task = db.query(DetectionTask).filter(
            DetectionTask.id == payload["task_id"], DetectionTask.user_id == current_user.id,
        ).first()
        if task is None:
            raise HTTPException(status_code=404, detail={"code": "RESOURCE_NOT_FOUND", "message": "detection task not found"})
        if task.status != "deleted":
            raise HTTPException(status_code=409, detail={"code": "UNDO_CONFLICT", "message": "detection task is no longer deleted"})
        task.status = payload.get("previous_status", "completed")
        db.commit()
    elif action.operation == "delete_knowledge_document":
        doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == payload["document_id"]).first()
        if doc is None or (doc.user_id != current_user.id and not current_user.is_superuser):
            raise HTTPException(status_code=404, detail={"code": "RESOURCE_NOT_FOUND", "message": "knowledge document not found"})
        if doc.status != "deleted":
            raise HTTPException(status_code=409, detail={"code": "UNDO_CONFLICT", "message": "knowledge document is no longer deleted"})
        doc.status = payload.get("previous_status", "indexed")
        db.commit()
    elif action.operation == "set_default_model":
        scene_service.set_default_model(db, payload["scene_id"], payload["previous_model_id"], current_user.id, current_user.is_superuser)
    elif action.operation == "rename_dataset":
        dataset = db.query(TrainingDataset).filter(TrainingDataset.path == payload["dataset_path"]).first()
        if dataset is None or (dataset.owner_id != current_user.id and not current_user.is_superuser):
            raise HTTPException(status_code=404, detail={"code": "RESOURCE_NOT_FOUND", "message": "training dataset not found"})
        dataset.display_name = payload.get("previous_display_name")
        dataset.description = payload.get("previous_description")
        db.commit()
    elif action.operation == "archive_dataset":
        dataset = db.query(TrainingDataset).filter(TrainingDataset.path == payload["dataset_path"]).first()
        if dataset is None or (dataset.owner_id != current_user.id and not current_user.is_superuser):
            raise HTTPException(status_code=404, detail={"code": "RESOURCE_NOT_FOUND", "message": "training dataset not found"})
        dataset.status = payload["previous_status"]
        db.commit()
    elif action.operation == "delete_dataset":
        dataset = db.query(TrainingDataset).filter(TrainingDataset.path == payload["dataset_path"]).first()
        if dataset is None or (dataset.owner_id != current_user.id and not current_user.is_superuser):
            raise HTTPException(status_code=404, detail={"code": "RESOURCE_NOT_FOUND", "message": "training dataset not found"})
        if dataset.status != "deleted":
            raise HTTPException(status_code=409, detail={"code": "UNDO_CONFLICT", "message": "training dataset is no longer deleted"})
        dataset.status = payload.get("previous_status", "active")
        db.commit()
    elif action.operation == "rename_model":
        model = db.query(ModelVersion).filter(
            ModelVersion.id == payload["model_version_id"], ModelVersion.scene_id == payload["scene_id"],
        ).first()
        if model is None or (model.owner_id != current_user.id and not current_user.is_superuser):
            raise HTTPException(status_code=404, detail={"code": "RESOURCE_NOT_FOUND", "message": "model not found"})
        model.model_name = payload.get("previous_model_name")
        model.version = payload.get("previous_version")
        db.commit()
    elif action.operation == "archive_model":
        model = db.query(ModelVersion).filter(
            ModelVersion.id == payload["model_version_id"], ModelVersion.scene_id == payload["scene_id"],
        ).first()
        if model is None or (model.owner_id != current_user.id and not current_user.is_superuser):
            raise HTTPException(status_code=404, detail={"code": "RESOURCE_NOT_FOUND", "message": "model not found"})
        model.status = payload["previous_status"]
        db.commit()
    elif action.operation == "delete_model":
        model = db.query(ModelVersion).filter(
            ModelVersion.id == payload["model_version_id"], ModelVersion.scene_id == payload["scene_id"],
        ).first()
        if model is None or (model.owner_id != current_user.id and not current_user.is_superuser):
            raise HTTPException(status_code=404, detail={"code": "RESOURCE_NOT_FOUND", "message": "model not found"})
        backup = Path(payload.get("backup_path", ""))
        target = Path(payload.get("model_path", ""))
        if model.status != "deleted" or not backup.is_file():
            raise HTTPException(status_code=409, detail={"code": "UNDO_CONFLICT", "message": "model backup is no longer available"})
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, target)
        backup.unlink(missing_ok=True)
        model.status = payload.get("previous_status", "active")
        model.cleanup_pending = False
        model.cleanup_error = None
        db.commit()
    else:
        raise HTTPException(status_code=400, detail={"code": "UNDO_UNSUPPORTED", "message": "undo operation is not supported"})
    return {"undone": True, "operation": action.operation}
