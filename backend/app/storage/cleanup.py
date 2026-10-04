"""Durable object-cleanup compensation, invoked by the API lifecycle."""
import logging
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config.settings import settings
from app.entity.db_models import ChatMessage, ChatSession, DetectionResult, DetectionTask, KnowledgeDocument, ModelVersion, TrainingDataset, TrainingTask, UndoAction
from app.services.scene_service import SceneService
from app.services.notification_service import notification_service
from app.storage.minio_client import MinIOClient

logger = logging.getLogger(__name__)


def cleanup_stale_agent_uploads(
    db: Session,
    upload_root: Path | None = None,
    max_age_seconds: int = 24 * 60 * 60,
) -> int:
    """Remove expired unreferenced chat attachments without breaking history."""
    root = (upload_root or (Path(tempfile.gettempdir()) / "rsod_uploads")).resolve()
    if not root.is_dir():
        return 0

    referenced: set[Path] = set()
    for message in db.query(ChatMessage).all():
        paths = list(message.image_paths or [])
        if message.image_path:
            paths.append(message.image_path)
        paths.extend(
            item.get("path")
            for item in (message.attachments or [])
            if isinstance(item, dict) and item.get("path")
        )
        for raw_path in paths:
            try:
                candidate = Path(raw_path).resolve()
            except (OSError, TypeError, ValueError):
                continue
            if candidate != root and root in candidate.parents:
                referenced.add(candidate)

    cutoff = datetime.now().timestamp() - max_age_seconds
    removed = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.resolve() in referenced:
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            logger.debug("Unable to remove stale chat attachment: %s", path.name)

    for directory in sorted((item for item in root.rglob("*") if item.is_dir()), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass
    return removed


def purge_expired_dataset_deletes(db: Session, limit: int = 100) -> int:
    """Finalize dataset deletes after their short undo window expires."""
    root = Path(settings.DATASET_BASE_DIR).resolve()
    actions = db.query(UndoAction).filter(
        UndoAction.operation.in_(("delete_dataset", "delete_model", "delete_chat_session", "delete_training_task", "delete_detection_task", "delete_knowledge_document")),
        UndoAction.consumed_at.is_(None),
        UndoAction.expires_at <= datetime.now(),
    ).limit(limit).all()
    purged = 0
    for action in actions:
        if action.operation == "delete_model":
            backup = Path(str((action.payload or {}).get("backup_path", ""))).resolve()
            undo_root = (Path(tempfile.gettempdir()) / "ssdd-model-undo").resolve()
            if undo_root in backup.parents and backup != undo_root:
                backup.unlink(missing_ok=True)
            db.delete(action)
            continue
        if action.operation == "delete_chat_session":
            session_uuid = str((action.payload or {}).get("session_uuid", ""))
            session = db.query(ChatSession).filter(ChatSession.session_uuid == session_uuid).first()
            if session and session.status == "deleted":
                db.delete(session)
            db.delete(action)
            continue
        if action.operation == "delete_training_task":
            task_id = (action.payload or {}).get("task_id")
            task = db.query(TrainingTask).filter(TrainingTask.id == task_id).first()
            if task and task.status == "deleted":
                task_uuid = task.task_uuid
                db.query(ModelVersion).filter(ModelVersion.training_task_id == task.id).update(
                    {"training_task_id": None}, synchronize_session=False,
                )
                db.delete(task)
                output_dir = Path.cwd() / settings.TRAIN_OUTPUT_DIR / f"task_{task_uuid}"
                if output_dir.is_dir():
                    shutil.rmtree(output_dir, ignore_errors=True)
            db.delete(action)
            purged += 1
            continue
        if action.operation == "delete_detection_task":
            task_id = (action.payload or {}).get("task_id")
            task = db.query(DetectionTask).filter(DetectionTask.id == task_id).first()
            if task and task.status == "deleted":
                cleanup_failed = False
                for result in task.results:
                    try:
                        for object_key, legacy_url in (
                            (result.original_object_key, result.image_path),
                            (result.annotated_object_key, result.annotated_image_url),
                        ):
                            if object_key:
                                MinIOClient().delete_file(object_key)
                            elif legacy_url:
                                MinIOClient().delete_by_url(legacy_url)
                    except Exception as exc:
                        cleanup_failed = True
                        result.cleanup_pending = True
                        result.cleanup_error = str(exc)
                        result.cleanup_retry_count = (result.cleanup_retry_count or 0) + 1
                        if task.user_id:
                            notification_service.safe_create(
                                db, task.user_id, "cleanup_failed", "Detection result cleanup failed",
                                "Detection result files could not be removed after the undo window; cleanup will be retried.",
                                task_id=task.id, resource_type="detection_task", resource_id=task.id,
                            )
                if not cleanup_failed:
                    db.delete(task)
                db.delete(action)
                purged += 1
            else:
                db.delete(action)
            continue
        if action.operation == "delete_knowledge_document":
            document_id = (action.payload or {}).get("document_id")
            document = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
            if document and document.status == "deleted":
                try:
                    if document.object_key:
                        MinIOClient().delete_file(document.object_key)
                    elif document.file_url:
                        MinIOClient().delete_by_url(document.file_url)
                    db.delete(document)
                except Exception as exc:
                    document.cleanup_pending = True
                    document.cleanup_error = str(exc)
                    document.cleanup_retry_count = (document.cleanup_retry_count or 0) + 1
                    if document.user_id:
                        notification_service.safe_create(
                            db, document.user_id, "cleanup_failed", "Knowledge document cleanup failed",
                            "A knowledge document could not be removed after the undo window; cleanup will be retried.",
                            resource_type="knowledge_document", resource_id=document.id,
                        )
            db.delete(action)
            purged += 1
            continue
        relative_path = str((action.payload or {}).get("dataset_path", ""))
        target = (root / relative_path).resolve()
        if target == root or root not in target.parents:
            logger.warning("Skipping unsafe expired dataset delete path=%s", relative_path)
            action.consumed_at = datetime.now()
            continue
        record = db.query(TrainingDataset).filter(TrainingDataset.path == relative_path).first()
        if record and record.status == "deleted":
            shutil.rmtree(target, ignore_errors=True)
            db.delete(record)
            purged += 1
        db.delete(action)
    if actions:
        db.commit()
    return purged


def retry_pending_cleanups(db: Session, limit: int = 100) -> dict:
    expired_dataset_deletes = purge_expired_dataset_deletes(db, limit)
    client = None

    def storage_client() -> MinIOClient:
        nonlocal client
        if client is None:
            client = MinIOClient()
        return client

    models = db.query(ModelVersion).filter(ModelVersion.cleanup_pending.is_(True)).limit(limit).all()
    documents = db.query(KnowledgeDocument).filter(KnowledgeDocument.cleanup_pending.is_(True)).limit(limit).all()
    results = db.query(DetectionResult).filter(DetectionResult.cleanup_pending.is_(True)).limit(limit).all()
    attempted = succeeded = 0

    for model in models:
        attempted += 1
        errors = SceneService._cleanup_model_files(model)
        if not errors:
            model.cleanup_pending = False
            model.cleanup_error = None
            succeeded += 1
        else:
            model.cleanup_retry_count = (model.cleanup_retry_count or 0) + 1
            model.cleanup_error = "; ".join(errors)
            logger.warning("pending model cleanup failed model_id=%s errors=%s", model.id, model.cleanup_error)
            if model.owner_id:
                notification_service.safe_create(
                    db, model.owner_id, "cleanup_failed", "Model cleanup failed",
                    "A model file cleanup is pending and will be retried.",
                    resource_type="model", resource_id=model.id,
                )

    for document in documents:
        try:
            attempted += 1
            if document.object_key:
                storage_client().delete_file(document.object_key)
            elif document.file_url:
                storage_client().delete_by_url(document.file_url)
            document.cleanup_pending = False
            document.cleanup_error = None
            db.delete(document)
            succeeded += 1
        except Exception as exc:
            document.cleanup_retry_count = (document.cleanup_retry_count or 0) + 1
            document.cleanup_error = str(exc)
            logger.exception("pending document cleanup failed key=%s", document.object_key)
            if document.user_id:
                notification_service.safe_create(
                    db, document.user_id, "cleanup_failed", "Knowledge document cleanup failed",
                    "A knowledge document cleanup is pending and will be retried.",
                    resource_type="knowledge_document", resource_id=document.id,
                )

    task_ids = set()
    for result in results:
        task_ids.add(result.task_id)
        failed = False
        for key, legacy_url in (
            (result.original_object_key, result.image_path),
            (result.annotated_object_key, result.annotated_image_url),
        ):
            if not key and not legacy_url:
                continue
            attempted += 1
            try:
                if key:
                    storage_client().delete_file(key)
                else:
                    storage_client().delete_by_url(legacy_url)
                succeeded += 1
            except Exception as exc:
                failed = True
                result.cleanup_retry_count = (result.cleanup_retry_count or 0) + 1
                result.cleanup_error = str(exc)
                logger.exception("pending detection result cleanup failed object_key=%s", key)
                task = db.get(DetectionTask, result.task_id)
                if task:
                    notification_service.safe_create(
                        db, task.user_id, "cleanup_failed", "Detection result cleanup failed",
                        "Detection result files are pending cleanup and will be retried.",
                        task_id=task.id, resource_type="detection_task", resource_id=task.id,
                    )
        if not failed:
            result.cleanup_pending = False
            result.cleanup_error = None

    for task_id in task_ids:
        task = db.get(DetectionTask, task_id)
        if task and all(not item.cleanup_pending for item in task.results):
            db.delete(task)
    db.commit()
    return {"attempted": attempted, "succeeded": succeeded, "expired_dataset_deletes": expired_dataset_deletes}


def find_orphan_objects(db: Session, prefix: str = "") -> list[str]:
    """Report objects not referenced by stable object keys; never delete them automatically."""
    client = MinIOClient()
    referenced = set()
    for model in db.query(ModelVersion.object_key).filter(ModelVersion.object_key.isnot(None)):
        referenced.add(model[0])
    for document in db.query(KnowledgeDocument.object_key).filter(KnowledgeDocument.object_key.isnot(None)):
        referenced.add(document[0])
    for result in db.query(DetectionResult.original_object_key, DetectionResult.annotated_object_key):
        referenced.update(key for key in result if key)
    return [item.object_name for item in client.list_objects(prefix) if item.object_name not in referenced]
