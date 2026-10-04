"""
检测场景服务层
处理检测场景（如"钢铁表面缺陷检测"）的创建、查询、更新与删除
对应任务文档步骤 11 的场景部分。
"""
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.entity.db_models import DetectionScene, ModelVersion


class SceneService:
    """检测场景服务"""

    @staticmethod
    def create_scene(
        db: Session,
        name: str,
        display_name: str,
        category: str,
        class_names: list[str],
        description: str | None = None,
        class_names_cn: dict | None = None,
        created_by: int | None = None,
    ) -> DetectionScene:
        if db.query(DetectionScene).filter(DetectionScene.name == name).first():
            raise HTTPException(status_code=400, detail="场景标识已存在")

        scene = DetectionScene(
            name=name,
            display_name=display_name,
            description=description,
            category=category,
            class_names=class_names,
            class_names_cn=class_names_cn,
            created_by=created_by,
        )
        db.add(scene)
        db.commit()
        db.refresh(scene)
        return scene

    @staticmethod
    def get_scene(db: Session, scene_id: int) -> DetectionScene:
        scene = db.query(DetectionScene).filter(DetectionScene.id == scene_id).first()
        if not scene:
            raise HTTPException(status_code=404, detail="检测场景不存在")
        return scene

    @staticmethod
    def list_scenes(db: Session, category: str | None = None, active_only: bool = True) -> list[DetectionScene]:
        query = db.query(DetectionScene)
        if active_only:
            query = query.filter(DetectionScene.is_active.is_(True))
        if category:
            query = query.filter(DetectionScene.category == category)
        return query.order_by(DetectionScene.created_at.desc()).all()

    @staticmethod
    def get_default_model(db: Session, scene_id: int) -> ModelVersion | None:
        """获取某场景当前的默认模型版本，切换检测模型时用"""
        return (
            db.query(ModelVersion)
            .filter(ModelVersion.scene_id == scene_id, ModelVersion.is_default.is_(True), ModelVersion.status == "active")
            .first()
        )

    @staticmethod
    def list_model_versions(
        db: Session, scene_id: int, user_id: int | None = None, is_superuser: bool = False
    ) -> list[ModelVersion]:
        """Return every user-visible model version for a scene.

        Detection clients must be able to choose an older active version as well
        as the current default. Deleted records stay hidden unless object cleanup
        is pending, in which case their owner needs a recovery entry point.
        """
        SceneService.get_scene(db, scene_id)
        query = db.query(ModelVersion).filter(
            ModelVersion.scene_id == scene_id,
            or_(ModelVersion.status != "deleted", ModelVersion.cleanup_pending.is_(True)),
        )
        if user_id is not None and not is_superuser:
            query = query.filter(or_(ModelVersion.is_builtin.is_(True), ModelVersion.owner_id == user_id))
        return query.order_by(ModelVersion.is_default.desc(), ModelVersion.created_at.desc()).all()

    @staticmethod
    def retry_model_cleanup(
        db: Session, scene_id: int, model_version_id: int, user_id: int, is_superuser: bool = False,
    ) -> ModelVersion:
        """Retry deleting a previously failed model object without reviving the model."""
        model = db.query(ModelVersion).filter(
            ModelVersion.id == model_version_id,
            ModelVersion.scene_id == scene_id,
            ModelVersion.cleanup_pending.is_(True),
        ).first()
        if not model:
            raise HTTPException(status_code=404, detail={"code": "RESOURCE_NOT_FOUND", "message": "没有待清理的模型资源"})
        if model.owner_id != user_id and not is_superuser:
            raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "无权重试该模型清理"})
        errors = SceneService._cleanup_model_files(model)
        if not errors:
            model.cleanup_pending = False
            model.cleanup_error = None
            db.commit()
            db.refresh(model)
            return model
        model.cleanup_retry_count = (model.cleanup_retry_count or 0) + 1
        model.cleanup_error = "; ".join(errors)
        db.commit()
        raise HTTPException(status_code=503, detail={"code": "CLEANUP_RETRY", "message": "模型文件清理仍未成功，请稍后重试"})

    @staticmethod
    def _cleanup_model_files(model: ModelVersion) -> list[str]:
        """Delete both local and object-store model copies, returning recoverable errors."""
        from pathlib import Path

        errors = []
        local_path = Path(model.model_path)
        if not local_path.is_absolute():
            local_path = Path(__file__).resolve().parents[3] / local_path
        try:
            local_path.unlink(missing_ok=True)
        except OSError as exc:
            errors.append(f"local file: {exc}")
        if model.object_key or model.minio_url:
            try:
                from app.storage.minio_client import MinIOClient
                client = MinIOClient()
                if model.object_key:
                    client.delete_file(model.object_key)
                else:
                    client.delete_by_url(model.minio_url)
            except Exception as exc:
                errors.append(f"object storage: {exc}")
        return errors

    @staticmethod
    def set_default_model(
        db: Session,
        scene_id: int,
        model_version_id: int,
        user_id: int | None = None,
        is_superuser: bool = False,
        expected_version: int | None = None,
    ) -> ModelVersion:
        """切换某场景的默认模型：先把旧默认取消，再把新的设为默认（同一事务）"""
        query = db.query(ModelVersion).filter(
            ModelVersion.id == model_version_id,
            ModelVersion.scene_id == scene_id,
            ModelVersion.status == "active",
        )
        if user_id is not None and not is_superuser:
            query = query.filter(or_(ModelVersion.is_builtin.is_(True), ModelVersion.owner_id == user_id))
        model = query.with_for_update().first()
        if not model:
            raise HTTPException(status_code=404, detail="模型版本不存在、不属于该场景或不可用")
        if expected_version is not None and model.resource_version != expected_version:
            raise HTTPException(status_code=409, detail={
                "code": "resource_changed",
                "current_version": model.resource_version,
            })

        try:
            db.query(ModelVersion).filter(
                ModelVersion.scene_id == scene_id, ModelVersion.is_default.is_(True)
            ).update({ModelVersion.is_default: False}, synchronize_session=False)
            model.is_default = True
            model.resource_version += 1
            db.commit()
            db.refresh(model)
            return model
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail={
                "code": "default_model_conflict",
                "message": "默认模型已被其他请求修改，请刷新后重试",
            }) from exc
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def get_model_version(
        db: Session, scene_id: int, model_version_id: int, user_id: int | None = None, is_superuser: bool = False
    ) -> ModelVersion:
        """Return one non-deleted model version belonging to a scene."""
        query = db.query(ModelVersion).filter(
            ModelVersion.id == model_version_id,
            ModelVersion.scene_id == scene_id,
            ModelVersion.status != "deleted",
        )
        if user_id is not None and not is_superuser:
            query = query.filter(or_(ModelVersion.is_builtin.is_(True), ModelVersion.owner_id == user_id))
        model = query.first()
        if not model:
            raise HTTPException(status_code=404, detail="模型版本不存在或不属于该场景")
        return model

    @staticmethod
    def create_uploaded_model(
        db: Session, scene_id: int, owner_id: int, version: str, model_name: str,
        model_type: str, model_path: str, file_size: int, description: str | None = None,
        object_key: str | None = None, minio_url: str | None = None,
    ) -> ModelVersion:
        SceneService.get_scene(db, scene_id)
        model = ModelVersion(
            scene_id=scene_id,
            owner_id=owner_id,
            version=version,
            model_name=model_name,
            model_type=model_type,
            model_path=model_path,
            file_size=file_size,
            description=description,
            object_key=object_key,
            minio_url=minio_url,
            is_builtin=False,
        )
        try:
            db.add(model)
            db.commit()
            db.refresh(model)
            return model
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def delete_model_version(
        db: Session, scene_id: int, model_version_id: int, user_id: int,
        is_superuser: bool = False, expected_version: int | None = None, cleanup_files: bool = True,
    ) -> ModelVersion:
        """Soft-delete a model without breaking detection-history references."""
        model = SceneService.get_model_version(db, scene_id, model_version_id, user_id, is_superuser)
        if model.is_builtin:
            raise HTTPException(status_code=403, detail="内置模型不可删除")
        if model.owner_id != user_id and not is_superuser:
            raise HTTPException(status_code=403, detail="无权删除该模型")
        if model.is_default:
            raise HTTPException(status_code=409, detail={"code": "RESOURCE_IN_USE", "message": "请先将其他模型设为默认模型"})
        if expected_version is not None and model.resource_version != expected_version:
            raise HTTPException(status_code=409, detail={
                "code": "resource_changed",
                "current_version": model.resource_version,
            })
        try:
            model.status = "deleted"
            model.is_default = False
            model.deleted_at = datetime.now()
            model.deleted_by_id = user_id
            model.purge_after = datetime.now() + timedelta(days=30)
            model.resource_version += 1
            db.commit()
            db.refresh(model)
            errors = SceneService._cleanup_model_files(model) if cleanup_files else []
            if errors:
                model.cleanup_pending = True
                model.cleanup_error = "; ".join(errors)
                model.cleanup_retry_count = (model.cleanup_retry_count or 0) + 1
                db.commit()
                raise HTTPException(status_code=503, detail={"code": "CLEANUP_RETRY", "message": "模型已软删除，但文件清理失败，请重试"})
            return model
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def restore_model_version(
        db: Session, scene_id: int, model_version_id: int, user_id: int,
        is_superuser: bool = False, expected_version: int | None = None,
    ) -> ModelVersion:
        query = db.query(ModelVersion).filter(
            ModelVersion.id == model_version_id,
            ModelVersion.scene_id == scene_id,
            ModelVersion.status == "deleted",
        )
        if not is_superuser:
            query = query.filter(ModelVersion.owner_id == user_id)
        model = query.with_for_update().first()
        if not model:
            raise HTTPException(status_code=404, detail="回收站中不存在该模型")
        if expected_version is not None and model.resource_version != expected_version:
            raise HTTPException(status_code=409, detail={
                "code": "resource_changed",
                "current_version": model.resource_version,
            })
        model.status = "active"
        model.is_default = False
        model.deleted_at = None
        model.deleted_by_id = None
        model.purge_after = None
        model.cleanup_error = None
        model.resource_version += 1
        db.commit()
        db.refresh(model)
        return model

    @staticmethod
    def archive_model_version(db, scene_id, model_version_id, user_id, is_superuser):
        model = SceneService.get_model_version(db, scene_id, model_version_id, user_id, is_superuser)
        if model.is_builtin or model.is_default:
            raise HTTPException(status_code=409, detail={"code": "RESOURCE_IN_USE", "message": "built-in or default model cannot be archived"})
        model.status = "archived" if model.status != "archived" else "active"
        db.commit(); db.refresh(model)
        return model

    @staticmethod
    def deactivate_scene(db: Session, scene_id: int) -> DetectionScene:
        """停用场景（不物理删除，避免破坏历史检测记录的外键引用）"""
        scene = SceneService.get_scene(db, scene_id)
        scene.is_active = False
        db.commit()
        db.refresh(scene)
        return scene


# 全局单例
scene_service = SceneService()
