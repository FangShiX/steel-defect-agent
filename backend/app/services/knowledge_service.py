"""
知识库服务层（RAG）
处理知识文档的入库、分块落库、向量相似度检索

权限边界原则（对应后续分工文档"数据库权限边界隔离"要求）：
  - user_id 为 NULL 的文档视为系统内置文档，所有登录用户可读，但只有管理员可删/改
  - 非管理员用户只能读取"自己上传的文档 + 系统文档"，看不到别人上传的私有资料
  - 向量检索（search_similar_chunks）同样按上述可见范围过滤，避免通过 RAG
    问答间接泄露别人上传的私有文档内容
"""

from app.storage.minio_client import MinIOClient
from fastapi import HTTPException
from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.entity.db_models import KnowledgeChunk, KnowledgeDocument, default_purge_after


class KnowledgeService:
    @staticmethod
    def _with_short_lived_url(doc: KnowledgeDocument) -> KnowledgeDocument:
        """Return a fresh signed URL only after visibility checks have passed."""
        if doc.object_key:
            # Keep the signed URL response-only; never mark it as a pending DB update.
            set_committed_value(doc, "file_url", MinIOClient().get_presigned_url(doc.object_key))
        else:
            # Legacy rows without an object key must not expose a persisted or
            # potentially permanent URL. The download endpoint will report the
            # missing object until the record is migrated.
            set_committed_value(doc, "file_url", None)
        return doc

    """知识库服务"""

    # ── 创建 ─────────────────────────────────────────────

    @staticmethod
    def create_document(
        db: Session,
        user_id: int | None,
        title: str,
        filename: str,
        file_url: str,
        object_key: str | None = None,
        file_type: str | None = None,
    ) -> KnowledgeDocument:
        """创建知识文档记录（原文件已上传至 MinIO 之后调用）。
        user_id=None 表示系统内置文档，只能由管理员触发（由路由层校验 is_superuser 后传入）。"""
        doc = KnowledgeDocument(
            user_id=user_id,
            title=title,
            filename=filename,
            file_url=file_url,
            object_key=object_key,
            file_type=file_type,
            status="processing",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return KnowledgeService._with_short_lived_url(doc)

    @staticmethod
    def add_chunks(db: Session, document_id: int, chunks: list[dict]) -> list[KnowledgeChunk]:
        """
        chunks 形如 [{"chunk_index": 0, "content": "...", "embedding": [...], "token_count": 120}, ...]
        调用方需要先完成文本切分和 embedding 计算，这里只负责落库并把文档状态置为 indexed。
        """
        doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="知识文档不存在")

        objs = [KnowledgeChunk(document_id=document_id, **c) for c in chunks]
        db.add_all(objs)
        doc.chunk_count = len(objs)
        doc.status = "indexed" if objs else "failed"

        db.commit()
        for o in objs:
            db.refresh(o)
        return objs

    @staticmethod
    def mark_failed(db: Session, document_id: int) -> None:
        """文本提取/切分/向量化失败时调用，避免文档卡在 processing 状态"""
        doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
        if doc:
            doc.status = "failed"
            db.commit()

    # ── 查询（带权限边界） ────────────────────────────────

    @staticmethod
    def _visibility_filter(query, user_id: int, is_superuser: bool):
        """非管理员只能看到：自己的文档 + 系统内置文档（user_id IS NULL）"""
        if not is_superuser:
            query = query.filter(
                or_(KnowledgeDocument.user_id == user_id, KnowledgeDocument.user_id.is_(None))
            )
        return query.filter(
            KnowledgeDocument.deletion_status == "active"
        )

    @staticmethod
    def get_document(
        db: Session, document_id: int, user_id: int, is_superuser: bool = False
    ) -> KnowledgeDocument:
        """根据 ID 获取知识文档，非管理员只能访问自己的文档或系统文档"""
        doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="知识文档不存在")
        if doc.deletion_status != "active":
            raise HTTPException(status_code=404, detail="知识文档不存在")
        if not is_superuser and doc.user_id is not None and doc.user_id != user_id:
            raise HTTPException(status_code=403, detail="无权访问该文档")
        if doc.status == "deleted":
            raise HTTPException(status_code=404, detail="知识文档不存在")
        return KnowledgeService._with_short_lived_url(doc)

    @staticmethod
    def list_documents(
        db: Session,
        user_id: int,
        is_superuser: bool = False,
        status: str | None = None,
    ) -> list[KnowledgeDocument]:
        """列出知识文档，可按处理状态筛选；非管理员只能看到自己的文档 + 系统文档"""
        query = db.query(KnowledgeDocument)
        query = KnowledgeService._visibility_filter(query, user_id, is_superuser)
        query = query.filter(KnowledgeDocument.status != "deleted")
        if status:
            query = query.filter(KnowledgeDocument.status == status)
        return [KnowledgeService._with_short_lived_url(doc) for doc in query.order_by(KnowledgeDocument.created_at.desc()).all()]

    @staticmethod
    def search_similar_chunks(
        db: Session,
        query_embedding: list[float],
        user_id: int,
        is_superuser: bool = False,
        top_k: int = 5,
        document_id: int | None = None,
    ) -> list[KnowledgeChunk]:
        """RAG 检索：按余弦距离取最相似的 top_k 个分块，供 Agent 回答问题时引用。
        只在当前用户可见的文档范围内检索（自己的 + 系统内置的，管理员不受限）。"""
        query = (
            db.query(KnowledgeChunk)
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .filter(KnowledgeDocument.status == "indexed")
            .filter(KnowledgeDocument.deletion_status == "active")
        )
        if not is_superuser:
            query = query.filter(
                or_(KnowledgeDocument.user_id == user_id, KnowledgeDocument.user_id.is_(None))
            )
        if document_id:
            # 显式指定 document_id 时也要过一遍权限边界，防止越权拼接一篇不可见的文档 ID
            KnowledgeService.get_document(db, document_id, user_id, is_superuser)
            query = query.filter(KnowledgeChunk.document_id == document_id)

        query = query.order_by(KnowledgeChunk.embedding.cosine_distance(query_embedding))
        return query.limit(top_k).all()

    # ── 删除 ─────────────────────────────────────────────

    @staticmethod
    def delete_document(
        db: Session, document_id: int, user_id: int, is_superuser: bool = False,
        expected_version: int | None = None,
    ) -> KnowledgeDocument:
        """Move a knowledge document to the recoverable recycle bin."""
        doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="知识文档不存在")
        if doc.user_id is None and not is_superuser:
            raise HTTPException(status_code=403, detail={"code": "BUILTIN_RESOURCE", "message": "内置知识文档只读"})
        if not is_superuser and doc.user_id != user_id:
            raise HTTPException(status_code=403, detail="无权删除该文档")
        if expected_version is not None and doc.resource_version != expected_version:
            raise HTTPException(status_code=409, detail={
                "code": "resource_changed",
                "current_version": doc.resource_version,
            })

        if doc.deletion_status != "active":
            raise HTTPException(status_code=409, detail="知识文档已在回收站中")
        doc.deletion_status = "trashed"
        doc.deleted_at = datetime.now()
        doc.deleted_by_id = user_id
        doc.purge_after = default_purge_after()
        doc.resource_version += 1
        db.commit()
        db.refresh(doc)
        return doc

    @staticmethod
    def restore_document(
        db: Session, document_id: int, user_id: int, can_manage_all: bool = False,
        expected_version: int | None = None,
    ) -> KnowledgeDocument:
        doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="知识文档不存在")
        if doc.user_id != user_id and not can_manage_all:
            raise HTTPException(status_code=403, detail="无权恢复该文档")
        if expected_version is not None and doc.resource_version != expected_version:
            raise HTTPException(status_code=409, detail={
                "code": "resource_changed",
                "current_version": doc.resource_version,
            })
        if doc.deletion_status != "trashed":
            raise HTTPException(status_code=409, detail="知识文档不在可恢复状态")
        doc.deletion_status = "active"
        doc.deleted_at = None
        doc.deleted_by_id = None
        doc.purge_after = None
        doc.resource_version += 1
        db.commit()
        db.refresh(doc)
        return doc


# 全局单例
knowledge_service = KnowledgeService()
