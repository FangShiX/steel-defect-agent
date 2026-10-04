"""
对话历史 API 路由
- POST   /api/chat/sessions                       新建会话
- GET    /api/chat/sessions                       会话列表（分页）
- GET    /api/chat/sessions/{session_uuid}        单个会话信息
- PATCH  /api/chat/sessions/{session_uuid}/title  重命名会话
- POST   /api/chat/sessions/{session_uuid}/archive 归档会话
- DELETE /api/chat/sessions/{session_uuid}        软删除会话（支持撤销）
- GET    /api/chat/sessions/{session_uuid}/messages  会话消息列表
- GET    /api/chat/sessions/{session_uuid}/history   会话+消息一次性拿

Agent 编排（api/agent.py 里的流式端点）是另一个模块的责任；这里只负责
数据库这一层的会话/消息 CRUD，前端 A/组长在实现 Agent 时调这些接口落库即可。
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database.session import get_db
from app.entity.db_models import User
from app.entity.schemas import (
    ChatHistoryResponse, ChatMessageResponse, ChatSessionCreate,
    ChatSessionResponse, PageResponse,
)
from app.services.chat_service import chat_service
from app.services.action_confirmation_service import action_confirmation_service
from app.services.operation_log_service import operation_log_service
from app.services.undo_service import undo_service
from app.services.resource_lifecycle_service import resource_lifecycle_service

router = APIRouter(prefix="/api/chat", tags=["对话历史"])


def _message_response(session_uuid: str, message) -> dict:
    data = ChatMessageResponse.model_validate(message).model_dump()
    data["attachments"] = [
        {key: item.get(key) for key in ("name", "content_type", "size") if item.get(key) is not None}
        for item in (message.attachments or [])
        if isinstance(item, dict)
    ]
    image_paths = message.image_paths or ([message.image_path] if message.image_path else [])
    data["has_image"] = bool(image_paths)
    data["image_urls"] = [
        f"/api/agent/sessions/{session_uuid}/messages/{message.id}/image?index={index}"
        for index, _ in enumerate(image_paths)
    ]
    return data


@router.post("/sessions", response_model=ChatSessionResponse, status_code=201)
def create_session(
    payload: ChatSessionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """新建会话；title 可以留空，第一条消息发来时会自动填充"""
    session = chat_service.create_session(db, current_user.id, title=payload.title)
    return session


@router.get("/sessions", response_model=PageResponse)
def list_sessions(
    status: Optional[str] = Query(default=None, description="active/archived，默认返回全部"),
    search: Optional[str] = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """会话列表，普通用户只能看自己的，管理员可看全部"""
    items, total = chat_service.list_sessions(
        db, user_id=current_user.id, is_superuser=current_user.is_superuser,
        status=status, search=search, page=page, page_size=page_size,
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if page_size else 0,
        "items": [ChatSessionResponse.model_validate(s) for s in items],
    }


@router.get("/sessions/{session_uuid}", response_model=ChatSessionResponse)
def get_session(
    session_uuid: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return chat_service.get_session(db, session_uuid, current_user.id, current_user.is_superuser)


@router.patch("/sessions/{session_uuid}/title", response_model=ChatSessionResponse)
def rename_session(
    session_uuid: str,
    title: str = Query(..., min_length=1, max_length=200),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = chat_service.get_session(db, session_uuid, current_user.id, current_user.is_superuser)
    previous_title = session.title or ""
    session = chat_service.rename_session(
        db, session_uuid, current_user.id, title, current_user.is_superuser
    )
    undo = undo_service.create(db, current_user.id, "rename_chat", {
        "session_uuid": session_uuid, "previous_title": previous_title,
    })
    data = ChatSessionResponse.model_validate(session).model_dump()
    data["undo_id"] = undo.undo_uuid
    operation_log_service.record(
        db, user=current_user, module="chat", action="rename_session",
        target_type="chat_session", target_id=session_uuid,
        description=f"Rename chat session {session_uuid}", request=request,
    )
    return data


@router.post("/sessions/{session_uuid}/archive", response_model=ChatSessionResponse)
def archive_session(
    session_uuid: str,
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """归档会话（软删除，仍保留在数据库中）"""
    session = chat_service.get_session(db, session_uuid, current_user.id, current_user.is_superuser)
    previous_status = session.status
    session = chat_service.archive_session(
        db, session_uuid, current_user.id, current_user.is_superuser
    )
    undo = undo_service.create(db, current_user.id, "archive_chat", {
        "session_uuid": session_uuid, "previous_status": previous_status,
    })
    data = ChatSessionResponse.model_validate(session).model_dump()
    data["undo_id"] = undo.undo_uuid
    operation_log_service.record(
        db, user=current_user, module="chat", action="archive_session",
        target_type="chat_session", target_id=session_uuid,
        description=f"Archive chat session {session_uuid}", request=request,
    )
    return data


@router.delete("/sessions/{session_uuid}")
def delete_session(
    session_uuid: str,
    confirmation_id: str | None = Header(default=None, alias="X-Confirmation-ID"),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = chat_service.get_session(db, session_uuid, current_user.id, current_user.is_superuser)
    action_confirmation_service.require_or_prepare(
        db, confirmation_uuid=confirmation_id, user_id=current_user.id,
        operation="delete_chat_session", target_type="chat_session", target_id=session_uuid,
        impact={"scope": "hide conversation and attachments during the undo window", "reversible": True},
        payload={"session_uuid": session_uuid},
        request_id=getattr(getattr(request, "state", None), "request_id", None),
    )
    previous_status = session.status
    session.status = "deleted"
    db.commit()
    undo_id = undo_service.create(db, current_user.id, "delete_chat_session", {
        "session_uuid": session_uuid,
        "previous_status": previous_status,
    }).undo_uuid
    operation_log_service.record(
        db, user=current_user, module="chat", action="delete_session",
        target_type="chat_session", target_id=session_uuid,
        description=f"Delete chat session {session_uuid}", request=request,
    )
    return {"message": "会话已删除", "undo_id": undo_id}


@router.get("/sessions/{session_uuid}/messages", response_model=list[ChatMessageResponse])
def list_messages(
    session_uuid: str,
    limit: Optional[int] = Query(default=None, ge=1, le=500,
                                    description="只取最近 N 条，Agent 拼上下文时用"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    messages = chat_service.list_messages(
        db, session_uuid, current_user.id, current_user.is_superuser, limit=limit
    )
    return [_message_response(session_uuid, message) for message in messages]


@router.get("/sessions/{session_uuid}/history", response_model=ChatHistoryResponse)
def get_history(
    session_uuid: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """一次性拿到会话 + 全部消息，供前端进入某个历史会话时使用"""
    session, messages = chat_service.get_history(
        db, session_uuid, current_user.id, current_user.is_superuser
    )
    return {
        "session": session,
        "messages": [_message_response(session_uuid, message) for message in messages],
    }


@router.post("/sessions/{session_uuid}/restore", response_model=ChatSessionResponse)
def restore_session(
    session_uuid: str,
    expected_version: int | None = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return chat_service.restore_session(
        db, session_uuid, current_user.id, expected_version
    )


@router.delete("/sessions/{session_uuid}/purge")
def purge_session(
    session_uuid: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.entity.db_models import ChatSession

    session = db.query(ChatSession).filter(
        ChatSession.session_uuid == session_uuid
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权彻底删除该会话")
    job = resource_lifecycle_service.purge_chat_session(db, session)
    return {"message": "会话已彻底删除", "cleanup_job_id": job.id, "status": job.status}




@router.post("/sessions/{session_uuid}/trash")
def trash_delete_session(
    session_uuid: str,
    expected_version: int | None = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """硬删除会话，同时级联删除所有消息"""
    session = chat_service.delete_session(
        db, session_uuid, current_user.id, False, expected_version
    )
    return {
        "message": "会话已移入回收站",
        "resource_version": session.resource_version,
        "purge_after": session.purge_after,
    }
