"""
RAG 知识库 API 路由
- POST   /api/knowledge/documents           上传知识文档（提取文本 → 分块 → 向量化 → 落库）
- GET    /api/knowledge/documents           列出知识文档（非管理员只看自己的 + 系统内置）
- GET    /api/knowledge/documents/{id}      文档详情（含分块列表，不含向量本身）
- DELETE /api/knowledge/documents/{id}      删除文档（非管理员只能删自己的）
- POST   /api/knowledge/search              RAG 相似度检索

权限边界：所有接口都要求登录；文档级别的可见/删除权限由 knowledge_service 统一把关，
避免在多个路由里重复写、写漏。
"""
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database.session import get_db
from app.entity.db_models import KnowledgeDocument, User
from app.entity.schemas import (
    KnowledgeChunkResponse,
    KnowledgeDocumentResponse,
    KnowledgeSearchRequest,
)
from app.services.document_parser import chunk_text, extract_text, guess_file_type
from app.services.embedding_service import embedding_service
from app.services.knowledge_service import knowledge_service
from app.services.action_confirmation_service import action_confirmation_service
from app.services.undo_service import undo_service
from app.services.operation_log_service import operation_log_service
from app.services.authorization_service import authorization_service
from app.services.resource_lifecycle_service import resource_lifecycle_service
from app.storage.minio_client import MinIOClient

router = APIRouter(prefix="/api/knowledge", tags=["知识库"])

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024


@router.post("/documents", response_model=KnowledgeDocumentResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    is_system: bool = Form(False),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    上传知识文档：txt/md/pdf/docx。
    is_system=True 表示登记为系统内置文档（对所有用户可读，只能被管理员删除），
    只有管理员可以传 True，否则忽略并按普通私有文档处理。
    """
    filename = file.filename or "untitled"
    if "\x00" in filename or any(ord(char) < 32 for char in filename):
        raise HTTPException(status_code=400, detail="文件名包含非法控制字符")
    filename = Path(filename).name
    file_type = guess_file_type(filename)

    content = await file.read(MAX_DOCUMENT_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="文档不能为空")
    if len(content) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="文档大小不能超过 20MB")

    if is_system:
        authorization_service.require_permission(db, current_user, "knowledge:system:manage")
    owner_id = None if is_system else current_user.id

    object_name = f"knowledge/{owner_id or 'system'}/{uuid4().hex}/{filename}"
    minio = MinIOClient()
    file_url = minio.upload_bytes(object_name, content, file.content_type or "application/octet-stream")
    try:
        doc = knowledge_service.create_document(
            db,
            user_id=owner_id,
            title=(title or filename).strip() or filename,
            filename=filename,
            file_url=file_url,
            object_key=object_name,
            file_type=file_type,
        )
    except Exception:
        try:
            minio.delete_file(object_name)
        except Exception:
            pass
        raise

    try:
        text = extract_text(filename, content)
        pieces = chunk_text(text)
        if not pieces:
            raise HTTPException(status_code=400, detail="文档解析结果为空，无法建立索引")

        vectors = embedding_service.embed_batch(pieces)
        chunks = [
            {"chunk_index": i, "content": piece, "embedding": vector, "token_count": len(piece)}
            for i, (piece, vector) in enumerate(zip(pieces, vectors))
        ]
        knowledge_service.add_chunks(db, doc.id, chunks)
        db.refresh(doc)
    except HTTPException:
        knowledge_service.mark_failed(db, doc.id)
        raise
    except Exception as exc:
        knowledge_service.mark_failed(db, doc.id)
        raise HTTPException(status_code=500, detail="知识文档索引失败，请稍后重试") from exc

    operation_log_service.record(
        db, user=current_user, module="knowledge", action="upload_document",
        target_type="knowledge_document", target_id=str(doc.id),
        description=f"Upload knowledge document {doc.id}", request=request,
    )
    return doc


@router.get("/documents", response_model=list[KnowledgeDocumentResponse])
def list_documents(
    status: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出可见的知识文档：自己上传的 + 系统内置的；管理员可看到全部"""
    # Administrators see private document metadata only through a dedicated,
    # audited admin surface; the user-facing API never exposes another user's
    # file URL or chunks.
    return knowledge_service.list_documents(db, user_id=current_user.id, is_superuser=False, status=status)


@router.get("/documents/{document_id}", response_model=KnowledgeDocumentResponse)
def get_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return knowledge_service.get_document(
        db, document_id, user_id=current_user.id, is_superuser=False
    )


@router.get("/documents/{document_id}/download", include_in_schema=False)
def download_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = knowledge_service.get_document(
        db, document_id, user_id=current_user.id, is_superuser=current_user.is_superuser
    )
    url = MinIOClient().get_presigned_url(doc.object_key) if doc.object_key else None
    if not url:
        raise HTTPException(status_code=404, detail="Knowledge document file not found")
    return RedirectResponse(url=url, status_code=307)


@router.get("/documents/{document_id}/chunks", response_model=list[KnowledgeChunkResponse])
def list_document_chunks(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查看某篇文档切分出的分块原文（不返回向量本身）"""
    doc = knowledge_service.get_document(
        db, document_id, user_id=current_user.id, is_superuser=False
    )
    return sorted(doc.chunks, key=lambda c: c.chunk_index)


@router.delete("/documents/{document_id}")
def delete_document(
    document_id: int,
    confirmation_id: str | None = Header(default=None, alias="X-Confirmation-ID"),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    action_confirmation_service.require_or_prepare(
        db, confirmation_uuid=confirmation_id, user_id=current_user.id,
        operation="delete_knowledge_document", target_type="knowledge_document", target_id=str(document_id),
        impact={"scope": "hide document and indexed chunks during the undo window", "reversible": True},
        payload={},
        request_id=getattr(getattr(request, "state", None), "request_id", None),
    )
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
    if doc is None:
        raise HTTPException(status_code=404, detail="知识文档不存在")
    if doc.user_id is None and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail={"code": "BUILTIN_RESOURCE", "message": "内置知识文档只读"})
    if doc.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="无权删除该文档")
    if doc.status == "deleted":
        raise HTTPException(status_code=404, detail="知识文档不存在")
    previous_status = doc.status
    doc.status = "deleted"
    db.commit()
    undo_id = undo_service.create(db, current_user.id, "delete_knowledge_document", {
        "document_id": doc.id,
        "previous_status": previous_status,
    }).undo_uuid
    operation_log_service.record(
        db, user=current_user, module="knowledge", action="delete_document",
        target_type="knowledge_document", target_id=str(document_id),
        description=f"Delete knowledge document {document_id}", request=request,
    )
    return {"message": "知识文档已删除", "undo_id": undo_id}


@router.post("/search", response_model=list[KnowledgeChunkResponse])
def search_knowledge(
    payload: KnowledgeSearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """RAG 相似度检索：把 query 转成向量后取最相似的 top_k 个分块，检索范围受权限边界约束"""
    query_embedding = embedding_service.embed_text(payload.query)
    return knowledge_service.search_similar_chunks(
        db,
        query_embedding=query_embedding,
        user_id=current_user.id,
        is_superuser=False,
        top_k=payload.top_k,
        document_id=payload.document_id,
    )


@router.post("/documents/{document_id}/restore", response_model=KnowledgeDocumentResponse)
def restore_document(
    document_id: int,
    expected_version: int | None = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    can_manage_all = authorization_service.has_permission(db, current_user, "knowledge:document:delete_all")
    return knowledge_service.restore_document(
        db, document_id, current_user.id, can_manage_all, expected_version
    )


@router.delete("/documents/{document_id}/purge")
def purge_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.entity.db_models import KnowledgeDocument

    document = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.id == document_id
    ).first()
    if not document:
        raise HTTPException(status_code=404, detail="知识文档不存在")
    can_manage_all = authorization_service.has_permission(
        db, current_user, "knowledge:document:delete_all"
    )
    if document.user_id != current_user.id and not can_manage_all:
        raise HTTPException(status_code=403, detail="无权彻底删除该文档")
    job = resource_lifecycle_service.purge_knowledge_document(db, document)
    return {"message": "知识文档已彻底删除", "cleanup_job_id": job.id, "status": job.status}




@router.post("/documents/{document_id}/trash")
def trash_delete_document(
    document_id: int,
    expected_version: int | None = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    can_delete_all = authorization_service.has_permission(db, current_user, "knowledge:document:delete_all")
    doc = knowledge_service.delete_document(
        db, document_id, user_id=current_user.id, is_superuser=can_delete_all,
        expected_version=expected_version,
    )
    return {
        "message": "知识文档已移入回收站",
        "resource_version": doc.resource_version,
        "purge_after": doc.purge_after,
    }
