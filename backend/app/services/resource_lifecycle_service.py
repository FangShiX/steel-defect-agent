"""Soft-delete, restore and auditable purge helpers for owned resources."""
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.entity.db_models import (
    ChatSession,
    DetectionTask,
    KnowledgeDocument,
    ModelVersion,
    ResourceCleanupJob,
    TrainingDataset,
    TrainingTask,
    default_purge_after,
)
from app.storage.minio_client import MinIOClient


class ResourceLifecycleService:
    @staticmethod
    def _check_version(resource, expected_version: int | None) -> None:
        if expected_version is not None and resource.resource_version != expected_version:
            raise HTTPException(status_code=409, detail={
                "code": "resource_changed",
                "message": "资源已被其他请求修改，请刷新后重试",
                "current_version": resource.resource_version,
            })

    @staticmethod
    def trash_detection_task(
        db: Session,
        task: DetectionTask,
        deleted_by_id: int,
        expected_version: int | None = None,
    ) -> DetectionTask:
        ResourceLifecycleService._check_version(task, expected_version)
        if task.deletion_status != "active":
            raise HTTPException(status_code=409, detail={
                "code": "already_deleted",
                "message": "资源已在回收站或清理队列中",
            })
        task.deletion_status = "trashed"
        task.deleted_at = datetime.now()
        task.deleted_by_id = deleted_by_id
        task.purge_after = default_purge_after()
        task.resource_version += 1
        db.commit()
        db.refresh(task)
        return task

    @staticmethod
    def restore_detection_task(
        db: Session,
        task: DetectionTask,
        expected_version: int | None = None,
    ) -> DetectionTask:
        ResourceLifecycleService._check_version(task, expected_version)
        if task.deletion_status not in {"trashed", "cleanup_failed"}:
            raise HTTPException(status_code=409, detail={
                "code": "not_restorable",
                "message": "该资源不在可恢复状态",
            })
        task.deletion_status = "active"
        task.deleted_at = None
        task.deleted_by_id = None
        task.purge_after = None
        task.cleanup_error = None
        task.resource_version += 1
        db.commit()
        db.refresh(task)
        return task

    @staticmethod
    def purge_detection_task(db: Session, task: DetectionTask) -> ResourceCleanupJob:
        if task.deletion_status not in {"trashed", "cleanup_failed"}:
            raise HTTPException(status_code=409, detail={
                "code": "purge_requires_trash",
                "message": "请先将资源移入回收站",
            })
        object_urls = sorted({
            value
            for result in task.results
            for value in (result.image_path, result.annotated_image_url)
            if value
        })
        job = ResourceCleanupJob(
            resource_type="detection_task",
            resource_id=task.public_task_id,
            owner_id=task.user_id,
            action="purge",
            status="running",
            object_keys=object_urls,
        )
        task.deletion_status = "cleanup_pending"
        db.add(job)
        db.commit()
        db.refresh(job)

        return ResourceLifecycleService._run_detection_purge(db, task, job)

    @staticmethod
    def _run_detection_purge(
        db: Session,
        task: DetectionTask,
        job: ResourceCleanupJob,
    ) -> ResourceCleanupJob:
        object_urls = list(job.object_keys or [])
        job.status = "running"
        job.error_message = None
        job.completed_at = None
        task.deletion_status = "cleanup_pending"
        db.commit()

        try:
            minio = None
            for value in object_urls:
                if minio is None:
                    minio = MinIOClient()
                minio.delete_by_url(value, suppress_errors=False)
        except Exception as exc:
            job.status = "failed"
            job.retry_count += 1
            job.error_message = str(exc)
            task.deletion_status = "cleanup_failed"
            task.cleanup_retry_count += 1
            task.cleanup_error = str(exc)
            db.commit()
            raise HTTPException(status_code=502, detail={
                "code": "storage_cleanup_failed",
                "cleanup_job_id": job.id,
                "message": "对象存储清理失败，已保留可重试任务",
            }) from exc

        job.status = "completed"
        job.completed_at = datetime.now()
        db.delete(task)
        db.commit()
        db.refresh(job)
        return job

    @staticmethod
    def purge_dataset(
        db: Session,
        dataset: TrainingDataset,
        dataset_root: Path,
        job: ResourceCleanupJob | None = None,
    ) -> ResourceCleanupJob:
        if dataset.deletion_status not in {"trashed", "cleanup_failed"}:
            raise HTTPException(status_code=409, detail={"code": "purge_requires_trash"})
        target = (dataset_root.resolve() / ".trash" / dataset.storage_key).resolve()
        trash_root = (dataset_root.resolve() / ".trash").resolve()
        if trash_root not in target.parents:
            raise HTTPException(status_code=400, detail="数据集存储路径无效")
        if job is None:
            job = ResourceCleanupJob(
                resource_type="training_dataset",
                resource_id=str(dataset.id),
                owner_id=dataset.owner_id,
                action="purge",
                status="running",
                object_keys=[str(target)],
            )
            db.add(job)
        job.status = "running"
        job.error_message = None
        job.completed_at = None
        dataset.deletion_status = "cleanup_pending"
        db.commit()
        db.refresh(job)
        try:
            if target.is_dir():
                shutil.rmtree(target)
        except Exception as exc:
            job.status = "failed"
            job.retry_count += 1
            job.error_message = str(exc)
            dataset.deletion_status = "cleanup_failed"
            dataset.cleanup_retry_count += 1
            dataset.cleanup_error = str(exc)
            db.commit()
            raise HTTPException(status_code=502, detail={
                "code": "storage_cleanup_failed",
                "cleanup_job_id": job.id,
            }) from exc
        job.status = "completed"
        job.completed_at = datetime.now()
        db.delete(dataset)
        db.commit()
        db.refresh(job)
        return job

    @staticmethod
    def purge_knowledge_document(
        db: Session,
        document: KnowledgeDocument,
        job: ResourceCleanupJob | None = None,
    ) -> ResourceCleanupJob:
        if document.deletion_status not in {"trashed", "cleanup_failed"}:
            raise HTTPException(status_code=409, detail={"code": "purge_requires_trash"})
        if job is None:
            job = ResourceCleanupJob(
                resource_type="knowledge_document",
                resource_id=str(document.id),
                owner_id=document.user_id,
                action="purge",
                status="running",
                object_keys=[document.object_key or document.file_url] if (document.object_key or document.file_url) else [],
            )
            db.add(job)
        job.status = "running"
        job.error_message = None
        job.completed_at = None
        document.deletion_status = "cleanup_pending"
        db.commit()
        db.refresh(job)
        try:
            minio = None
            for value in job.object_keys or []:
                if minio is None:
                    minio = MinIOClient()
                if value.startswith(("http://", "https://")):
                    minio.delete_by_url(value, suppress_errors=False)
                else:
                    minio.delete_file(value)
        except Exception as exc:
            job.status = "failed"
            job.retry_count += 1
            job.error_message = str(exc)
            document.deletion_status = "cleanup_failed"
            document.cleanup_retry_count += 1
            document.cleanup_error = str(exc)
            db.commit()
            raise HTTPException(status_code=502, detail={
                "code": "storage_cleanup_failed",
                "cleanup_job_id": job.id,
            }) from exc
        job.status = "completed"
        job.completed_at = datetime.now()
        db.delete(document)
        db.commit()
        db.refresh(job)
        return job

    @staticmethod
    def purge_chat_session(
        db: Session,
        session: ChatSession,
        job: ResourceCleanupJob | None = None,
    ) -> ResourceCleanupJob:
        if session.deletion_status not in {"trashed", "cleanup_failed"}:
            raise HTTPException(status_code=409, detail={"code": "purge_requires_trash"})
        attachments = sorted({
            value
            for message in session.messages
            for value in ([message.image_path] + list(message.image_paths or []) + [item.get("path") for item in (message.attachments or [])])
            if value
        })
        if job is None:
            job = ResourceCleanupJob(
                resource_type="chat_session",
                resource_id=session.session_uuid,
                owner_id=session.user_id,
                action="purge",
                status="running",
                object_keys=attachments,
            )
            db.add(job)
        job.status = "running"
        job.error_message = None
        job.completed_at = None
        session.deletion_status = "cleanup_pending"
        db.commit()
        db.refresh(job)
        try:
            minio = None
            from app.api.agent import UPLOAD_DIR, ARTIFACT_DIR, _artifact_filenames
            from app.core.artifact_access import unregister_artifact
            upload_root = (Path(UPLOAD_DIR) / str(session.user_id)).resolve()
            for value in job.object_keys or []:
                if value.startswith(("http://", "https://")):
                    if minio is None:
                        minio = MinIOClient()
                    minio.delete_by_url(value, suppress_errors=False)
                    continue
                attachment = Path(value).resolve()
                if upload_root not in attachment.parents:
                    raise ValueError("聊天附件不在受控上传目录中")
                if attachment.is_file():
                    attachment.unlink()
            artifact_root = Path(ARTIFACT_DIR).resolve()
            for message in session.messages:
                for filename in _artifact_filenames(message.tool_calls):
                    artifact = (artifact_root / filename).resolve()
                    if artifact.parent != artifact_root:
                        raise ValueError("聊天产物不在受控目录中")
                    artifact.unlink(missing_ok=True)
                    unregister_artifact(filename)
        except Exception as exc:
            job.status = "failed"
            job.retry_count += 1
            job.error_message = str(exc)
            session.deletion_status = "cleanup_failed"
            db.commit()
            raise HTTPException(status_code=502, detail={
                "code": "storage_cleanup_failed",
                "cleanup_job_id": job.id,
            }) from exc
        job.status = "completed"
        job.completed_at = datetime.now()
        db.delete(session)
        db.commit()
        db.refresh(job)
        return job

    @staticmethod
    def purge_training_task(
        db: Session,
        task: TrainingTask,
        job: ResourceCleanupJob | None = None,
    ) -> ResourceCleanupJob:
        if task.deletion_status not in {"trashed", "cleanup_failed"}:
            raise HTTPException(status_code=409, detail={"code": "purge_requires_trash"})
        output_root = Path(settings.TRAIN_OUTPUT_DIR)
        if not output_root.is_absolute():
            output_root = Path(__file__).resolve().parents[3] / output_root
        output_root = output_root.resolve()
        output_dir = (output_root / f"task_{task.task_uuid}").resolve()
        if output_root not in output_dir.parents:
            raise HTTPException(status_code=400, detail="训练输出路径无效")
        if job is None:
            job = ResourceCleanupJob(
                resource_type="training_task",
                resource_id=str(task.id),
                owner_id=task.user_id,
                action="purge",
                status="running",
                object_keys=[str(output_dir)],
            )
            db.add(job)
        job.status = "running"
        job.error_message = None
        job.completed_at = None
        db.commit()
        db.refresh(job)
        try:
            if output_dir.is_dir():
                shutil.rmtree(output_dir)
        except Exception as exc:
            job.status = "failed"
            job.retry_count += 1
            job.error_message = str(exc)
            task.deletion_status = "cleanup_failed"
            task.cleanup_error = str(exc)
            db.commit()
            raise HTTPException(status_code=502, detail={
                "code": "storage_cleanup_failed",
                "cleanup_job_id": job.id,
            }) from exc
        db.query(ModelVersion).filter(
            ModelVersion.training_task_id == task.id
        ).update({ModelVersion.training_task_id: None}, synchronize_session=False)
        job.status = "completed"
        job.completed_at = datetime.now()
        db.delete(task)
        db.commit()
        db.refresh(job)
        return job

    @staticmethod
    def purge_model_version(
        db: Session,
        model: ModelVersion,
        job: ResourceCleanupJob | None = None,
    ) -> ResourceCleanupJob:
        if model.status != "deleted":
            raise HTTPException(status_code=409, detail={"code": "purge_requires_trash"})
        if db.query(DetectionTask).filter(
            DetectionTask.model_version_id == model.id
        ).first():
            raise HTTPException(status_code=409, detail={
                "code": "model_still_referenced",
                "message": "模型仍被检测历史引用，不能彻底删除",
            })
        project_root = Path(__file__).resolve().parents[3]
        models_root = (project_root / "models").resolve()
        model_path = (project_root / model.model_path).resolve()
        if models_root not in model_path.parents:
            raise HTTPException(status_code=400, detail="模型文件不在受控目录中")
        object_keys = [value for value in (model.minio_url, str(model_path)) if value]
        if job is None:
            job = ResourceCleanupJob(
                resource_type="model_version",
                resource_id=str(model.id),
                owner_id=model.owner_id,
                action="purge",
                status="running",
                object_keys=object_keys,
            )
            db.add(job)
        job.status = "running"
        job.error_message = None
        job.completed_at = None
        db.commit()
        db.refresh(job)
        try:
            if model.minio_url:
                MinIOClient().delete_by_url(model.minio_url, suppress_errors=False)
            if model_path.is_file():
                model_path.unlink()
        except Exception as exc:
            job.status = "failed"
            job.retry_count += 1
            job.error_message = str(exc)
            model.cleanup_retry_count += 1
            model.cleanup_error = str(exc)
            db.commit()
            raise HTTPException(status_code=502, detail={
                "code": "storage_cleanup_failed",
                "cleanup_job_id": job.id,
            }) from exc
        job.status = "completed"
        job.completed_at = datetime.now()
        db.delete(model)
        db.commit()
        db.refresh(job)
        return job

    @staticmethod
    def retry_cleanup_job(db: Session, job_id: int) -> ResourceCleanupJob:
        job = db.query(ResourceCleanupJob).filter(
            ResourceCleanupJob.id == job_id
        ).with_for_update().first()
        if not job:
            raise HTTPException(status_code=404, detail="清理任务不存在")
        if job.status != "failed":
            raise HTTPException(status_code=409, detail={
                "code": "cleanup_job_not_retryable",
                "status": job.status,
            })

        if job.resource_type == "detection_task" and job.action == "purge":
            task = db.query(DetectionTask).filter(
                DetectionTask.public_task_id == job.resource_id
            ).first()
            if not task:
                job.status = "completed"
                job.error_message = None
                job.completed_at = datetime.now()
                db.commit()
                db.refresh(job)
                return job
            return ResourceLifecycleService._run_detection_purge(db, task, job)

        if job.resource_type == "user" and job.action == "cascade_delete":
            from app.services.user_service import user_service

            return user_service.delete_user_cascade(
                db,
                int(job.resource_id),
                cleanup_job_id=job.id,
            )

        if job.resource_type == "training_dataset" and job.action == "purge":
            dataset = db.query(TrainingDataset).filter(
                TrainingDataset.id == int(job.resource_id)
            ).first()
            if dataset:
                dataset_root = (
                    Path(__file__).resolve().parents[3] / settings.DATASET_BASE_DIR
                ).resolve()
                return ResourceLifecycleService.purge_dataset(
                    db, dataset, dataset_root, job
                )

        if job.resource_type == "knowledge_document" and job.action == "purge":
            document = db.query(KnowledgeDocument).filter(
                KnowledgeDocument.id == int(job.resource_id)
            ).first()
            if document:
                return ResourceLifecycleService.purge_knowledge_document(
                    db, document, job
                )

        if job.resource_type == "chat_session" and job.action == "purge":
            session = db.query(ChatSession).filter(
                ChatSession.session_uuid == job.resource_id
            ).first()
            if session:
                return ResourceLifecycleService.purge_chat_session(db, session, job)

        if job.resource_type == "training_task" and job.action == "purge":
            task = db.query(TrainingTask).filter(
                TrainingTask.id == int(job.resource_id)
            ).first()
            if task:
                return ResourceLifecycleService.purge_training_task(db, task, job)

        if job.resource_type == "model_version" and job.action == "purge":
            model = db.query(ModelVersion).filter(
                ModelVersion.id == int(job.resource_id)
            ).first()
            if model:
                return ResourceLifecycleService.purge_model_version(db, model, job)

        if job.action == "purge" and job.resource_type in {
            "training_dataset", "knowledge_document", "chat_session",
            "training_task", "model_version",
        }:
            job.status = "completed"
            job.error_message = None
            job.completed_at = datetime.now()
            db.commit()
            db.refresh(job)
            return job

        raise HTTPException(status_code=409, detail={
            "code": "cleanup_job_type_not_supported",
            "resource_type": job.resource_type,
            "action": job.action,
        })

    @staticmethod
    def list_cleanup_jobs(
        db: Session,
        *,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ResourceCleanupJob], int]:
        query = db.query(ResourceCleanupJob)
        if status:
            query = query.filter(ResourceCleanupJob.status == status)
        total = query.count()
        items = (
            query.order_by(ResourceCleanupJob.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total


resource_lifecycle_service = ResourceLifecycleService()
