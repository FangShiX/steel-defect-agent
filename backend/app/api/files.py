"""通用文件落库与生命周期接口。"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database.session import get_db
from app.entity.db_models import User
from app.entity.schemas import StoredFileResponse
from app.services.file_service import file_service
from app.storage.minio_client import MinIOClient

router = APIRouter(prefix="/api/files", tags=["文件生命周期"])


def _response(record):
    data = StoredFileResponse.model_validate(record)
    if record.status not in {"deleted", "cleanup_pending"}:
        try:
            data.download_url = MinIOClient().get_presigned_url(record.object_key)
        except Exception:
            data.download_url = None
    return data


@router.post("", response_model=StoredFileResponse, status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    resource_type: str = Form("generic"),
    resource_id: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chunks, size = [], 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > file_service.MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="File exceeds the 100 MB limit")
        chunks.append(chunk)
    data = b"".join(chunks)
    record = file_service.create(
        db, current_user.id, file.filename or "file", file.content_type,
        data, resource_type, resource_id,
    )
    return _response(record)


@router.get("", response_model=list[StoredFileResponse])
def list_files(
    include_deleted: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return [_response(item) for item in file_service.list(
        db, current_user.id, current_user.is_superuser, include_deleted
    )]


@router.get("/{file_id}", response_model=StoredFileResponse)
def get_file(
    file_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _response(file_service.get(db, file_id, current_user.id, current_user.is_superuser))


@router.post("/{file_id}/archive", response_model=StoredFileResponse)
def archive_file(file_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _response(file_service.update_status(db, file_id, current_user.id, current_user.is_superuser, "archived"))


@router.post("/{file_id}/restore", response_model=StoredFileResponse)
def restore_file(file_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _response(file_service.update_status(db, file_id, current_user.id, current_user.is_superuser, "active"))


@router.delete("/{file_id}", response_model=StoredFileResponse)
def delete_file(file_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _response(file_service.delete(db, file_id, current_user.id, current_user.is_superuser))
