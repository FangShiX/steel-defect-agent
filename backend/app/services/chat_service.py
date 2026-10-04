"""
对话服务层
负责 chat_sessions / chat_messages 两张表的落库和查询。

设计定位：
- 这是数据库这一层的 service，只做 CRUD 和权限过滤，不涉及 Agent 编排、
  LLM 调用、SSE 流式推送——那些是前端 A 和组长在 api/agent.py 里做的事
- Agent 侧需要把每一轮对话（用户消息 + 助手回复 + 工具调用记录）落库时，
  直接调用这里的 append_user_message / append_assistant_message 即可
- 会话本身通过 session_uuid（对外暴露）而不是整数 id 定位，避免 id 被遍历猜测

权限模型：
- 每次操作都会校验 session.user_id == current_user.id（管理员可绕过）
- 前端只能拿到自己的会话列表和消息，看不到别人的
"""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.entity.db_models import ChatSession, ChatMessage, default_purge_after


class ChatService:
    """对话会话与消息服务"""

    # ── 会话生命周期 ─────────────────────────────────────

    @staticmethod
    def create_session(
        db: Session,
        user_id: int,
        title: Optional[str] = None,
    ) -> ChatSession:
        """新建对话会话。session_uuid 自动生成，前端后续用它引用会话。"""
        session = ChatSession(
            user_id=user_id,
            session_uuid=str(uuid.uuid4()),
            title=title,
            status="active",
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        if session.status == "deleted":
            raise HTTPException(status_code=404, detail="浼氳瘽涓嶅瓨鍦?")
        return session

    @staticmethod
    def get_session(
        db: Session,
        session_uuid: str,
        user_id: int,
        is_superuser: bool = False,
    ) -> ChatSession:
        """按 UUID 获取会话，非管理员只能访问自己的"""
        session = (
            db.query(ChatSession)
            .filter(ChatSession.session_uuid == session_uuid)
            .first()
        )
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        if session.deletion_status != "active":
            raise HTTPException(status_code=404, detail="会话不存在")
        if session.user_id != user_id and not is_superuser:
            raise HTTPException(status_code=403, detail="无权访问该会话")
        return session

    @staticmethod
    def list_sessions(
        db: Session,
        user_id: int,
        is_superuser: bool = False,
        status: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ChatSession], int]:
        """分页查询会话列表，按最后消息时间倒序（没有消息的按创建时间兜底）"""
        query = db.query(ChatSession).filter(ChatSession.deletion_status == "active")
        if not is_superuser:
            query = query.filter(ChatSession.user_id == user_id)
        query = query.filter(ChatSession.status != "deleted")
        if status:
            query = query.filter(ChatSession.status == status)
        if search:
            query = query.filter(ChatSession.title.ilike(f"%{search.strip()}%"))

        total = query.count()
        items = (
            query.order_by(
                ChatSession.last_message_at.desc().nullslast(),
                ChatSession.created_at.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    @staticmethod
    def rename_session(
        db: Session,
        session_uuid: str,
        user_id: int,
        title: str,
        is_superuser: bool = False,
    ) -> ChatSession:
        """重命名会话"""
        session = ChatService.get_session(db, session_uuid, user_id, is_superuser)
        session.title = title
        db.commit()
        db.refresh(session)
        return session

    @staticmethod
    def archive_session(
        db: Session,
        session_uuid: str,
        user_id: int,
        is_superuser: bool = False,
    ) -> ChatSession:
        """归档会话（软删除，仍保留在数据库中，但列表默认不显示）"""
        session = ChatService.get_session(db, session_uuid, user_id, is_superuser)
        session.status = "archived"
        db.commit()
        db.refresh(session)
        return session

    @staticmethod
    def delete_session(
        db: Session,
        session_uuid: str,
        user_id: int,
        is_superuser: bool = False,
        expected_version: int | None = None,
    ) -> ChatSession:
        """Move a conversation and its attachments to the recycle bin."""
        session = ChatService.get_session(db, session_uuid, user_id, is_superuser)
        if expected_version is not None and session.resource_version != expected_version:
            raise HTTPException(status_code=409, detail={
                "code": "resource_changed",
                "current_version": session.resource_version,
            })
        session.deletion_status = "trashed"
        session.deleted_at = datetime.now()
        session.deleted_by_id = user_id
        session.purge_after = default_purge_after()
        session.resource_version += 1
        db.commit()
        db.refresh(session)
        return session

    @staticmethod
    def restore_session(
        db: Session,
        session_uuid: str,
        user_id: int,
        expected_version: int | None = None,
    ) -> ChatSession:
        session = db.query(ChatSession).filter(ChatSession.session_uuid == session_uuid).first()
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        if session.user_id != user_id:
            raise HTTPException(status_code=403, detail="无权恢复该会话")
        if expected_version is not None and session.resource_version != expected_version:
            raise HTTPException(status_code=409, detail={
                "code": "resource_changed",
                "current_version": session.resource_version,
            })
        if session.deletion_status != "trashed":
            raise HTTPException(status_code=409, detail="会话不在可恢复状态")
        session.deletion_status = "active"
        session.deleted_at = None
        session.deleted_by_id = None
        session.purge_after = None
        session.resource_version += 1
        db.commit()
        db.refresh(session)
        return session

    # ── 消息读写 ─────────────────────────────────────────

    @staticmethod
    def append_message(
        db: Session,
        session_uuid: str,
        user_id: int,
        role: str,
        content: str,
        *,
        agent_used: Optional[str] = None,
        tool_calls: Optional[list] = None,
        tool_result: Optional[str] = None,
        tokens_used: Optional[int] = None,
        latency_ms: Optional[int] = None,
        is_superuser: bool = False,
    ) -> ChatMessage:
        """
        向会话追加一条消息，同时更新会话的 message_count / last_message_at。
        role 取值：user / assistant / tool / system

        Agent 编排层的典型调用：
            append_message(db, uuid, uid, role="user", content="...")
            # ... Agent 处理 ...
            append_message(db, uuid, uid, role="assistant", content="...",
                            agent_used="detection", tool_calls=[...],
                            tokens_used=1024, latency_ms=850)
        """
        session = ChatService.get_session(db, session_uuid, user_id, is_superuser)

        message = ChatMessage(
            session_id=session.id,
            role=role,
            content=content,
            agent_used=agent_used,
            tool_calls=tool_calls,
            tool_result=tool_result,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
        )
        db.add(message)

        # 更新会话元数据
        session.message_count = (session.message_count or 0) + 1
        session.last_message_at = datetime.now()
        # 如果会话还没有标题，用第一条用户消息前 40 个字符作为默认标题
        if not session.title and role == "user":
            session.title = content[:40].strip() or None

        db.commit()
        db.refresh(message)
        return message

    @staticmethod
    def list_messages(
        db: Session,
        session_uuid: str,
        user_id: int,
        is_superuser: bool = False,
        limit: Optional[int] = None,
    ) -> list[ChatMessage]:
        """
        按创建时间正序返回一个会话下的所有消息。
        limit 可选：Agent 拼上下文时可以只取最近 N 条，避免 token 爆炸。
        """
        session = ChatService.get_session(db, session_uuid, user_id, is_superuser)

        query = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session.id)
            .order_by(ChatMessage.created_at.asc())
        )
        if limit is not None and limit > 0:
            # 需要最近 N 条：倒序取 N 条再反转，保证仍按时间正序返回
            messages = (
                db.query(ChatMessage)
                .filter(ChatMessage.session_id == session.id)
                .order_by(ChatMessage.created_at.desc())
                .limit(limit)
                .all()
            )
            messages.reverse()
            return messages
        return query.all()

    @staticmethod
    def get_history(
        db: Session,
        session_uuid: str,
        user_id: int,
        is_superuser: bool = False,
    ) -> tuple[ChatSession, list[ChatMessage]]:
        """一次性拿到会话和它的所有消息，供 /chat/history 类接口使用"""
        session = ChatService.get_session(db, session_uuid, user_id, is_superuser)
        messages = ChatService.list_messages(db, session_uuid, user_id, is_superuser)
        return session, messages


# 全局单例
chat_service = ChatService()
