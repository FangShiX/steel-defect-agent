"""数据库文件台账与 MinIO 对象生命周期服务。"""
import hashlib
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.entity.db_models import StoredFile
from app.storage.minio_client import MinIOClient


class FileService:
    MAX_FILE_SIZE = 100 * 1024 * 1024
    ALLOWED_TYPES = {"image", "video", "dataset", "model", "document", "generic"}

    @staticmethod
    def _assert_access(record: StoredFile, user_id: int, is_superuser: bool) -> None:
        if record.user_id != user_id and not is_superuser:
            raise HTTPException(status_code=403, detail="无权访问该文件")

    @staticmethod
    def _object_key(resource_type: str, filename: str) -> str:
        suffix = Path(filename or "file").suffix.lower()[:20]
        return f"files/{resource_type}/{datetime.now():%Y/%m/%d}/{uuid.uuid4().hex}{suffix}"

    def create(self, db: Session, user_id: int, filename: str, content_type: str | None,
               data: bytes, resource_type: str = "generic", resource_id: str | None = None) -> StoredFile:
        if resource_type not in self.ALLOWED_TYPES:
            raise HTTPException(status_code=400, detail="不支持的资源类型")
        if not filename:
            raise HTTPException(status_code=400, detail="文件名不能为空")
        if len(data) > self.MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="文件不能超过100 MB")

        object_key = self._object_key(resource_type, filename)
        checksum = hashlib.sha256(data).hexdigest()
        client = MinIOClient()
        try:
            client.upload_bytes(object_key, data, content_type or "application/octet-stream")
        except Exception as exc:
            raise HTTPException(status_code=502, detail="对象存储上传失败，请稍后重试") from exc

        record = StoredFile(
            user_id=user_id,
            object_key=object_key,
            original_filename=filename[:255],
            content_type=content_type,
            file_size=len(data),
            checksum=checksum,
            resource_type=resource_type,
            resource_id=resource_id,
            status="active",
        )
        db.add(record)
        try:
            db.commit()
            db.refresh(record)
        except Exception:
            db.rollback()
            try:
                client.delete_file(object_key)
            except Exception:
                pass
            raise
        return record

    def list(self, db: Session, user_id: int, is_superuser: bool, include_deleted: bool = False):
        query = db.query(StoredFile)
        if not is_superuser:
            query = query.filter(StoredFile.user_id == user_id)
        if not include_deleted:
            query = query.filter(StoredFile.status != "deleted")
        return query.order_by(StoredFile.created_at.desc()).all()

    def get(self, db: Session, file_id: int, user_id: int, is_superuser: bool) -> StoredFile:
        record = db.query(StoredFile).filter(StoredFile.id == file_id).first()
        if record is None:
            raise HTTPException(status_code=404, detail="文件记录不存在")
        self._assert_access(record, user_id, is_superuser)
        return record

    def update_status(self, db: Session, file_id: int, user_id: int, is_superuser: bool, status: str) -> StoredFile:
        if status not in {"archived", "active"}:
            raise HTTPException(status_code=400, detail="生命周期状态无效")
        record = self.get(db, file_id, user_id, is_superuser)
        if record.status in {"deleted", "cleanup_pending"}:
            raise HTTPException(status_code=409, detail="已删除或待清理文件不能恢复")
        record.status = status
        record.archived_at = datetime.now() if status == "archived" else None
        record.updated_at = datetime.now()
        db.commit()
        db.refresh(record)
        return record

    def delete(self, db: Session, file_id: int, user_id: int, is_superuser: bool) -> StoredFile:
        record = self.get(db, file_id, user_id, is_superuser)
        if record.status == "deleted":
            return record
        client = MinIOClient()
        record.status = "deleted"
        record.deleted_at = datetime.now()
        record.updated_at = datetime.now()
        record.cleanup_error = None
        try:
            client.delete_file(record.object_key)
        except Exception as exc:
            record.status = "cleanup_pending"
            record.cleanup_error = str(exc)[:2000]
        db.commit()
        db.refresh(record)
        return record


file_service = FileService()
