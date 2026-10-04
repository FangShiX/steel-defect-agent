"""Tests for chat_service and operation_log_service (both new)."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.entity.db_models import User, OperationLog
from app.services.chat_service import chat_service
from app.services.operation_log_service import operation_log_service


def _make_user(db, username):
    user = User(
        username=username,
        email=f"{username}@example.com",
        hashed_password="x",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ─────────────────────────── chat_service ────────────────────────────

def test_create_session_generates_uuid(db_session):
    user = _make_user(db_session, "alice")
    session = chat_service.create_session(db_session, user.id, title="test")

    assert session.session_uuid
    assert len(session.session_uuid) >= 32  # 是有效的 uuid4
    assert session.user_id == user.id
    assert session.status == "active"
    assert session.message_count == 0


def test_append_message_updates_session_metadata(db_session):
    user = _make_user(db_session, "alice")
    session = chat_service.create_session(db_session, user.id)

    msg = chat_service.append_message(
        db_session, session.session_uuid, user.id,
        role="user", content="第一条消息，会成为标题",
    )

    db_session.refresh(session)
    assert msg.session_id == session.id
    assert msg.role == "user"
    assert session.message_count == 1
    assert session.last_message_at is not None
    # 首条 user 消息会自动补标题
    assert session.title == "第一条消息，会成为标题"


def test_append_message_auto_title_only_uses_first_user_message(db_session):
    """标题一旦有值就不再被后续消息覆盖"""
    user = _make_user(db_session, "alice")
    session = chat_service.create_session(db_session, user.id, title="预设标题")

    chat_service.append_message(
        db_session, session.session_uuid, user.id, role="user", content="后面来的消息",
    )
    db_session.refresh(session)
    assert session.title == "预设标题"


def test_users_only_see_own_sessions(db_session):
    """普通用户不能查看别人的会话，管理员可以"""
    alice = _make_user(db_session, "alice")
    bob = _make_user(db_session, "bob")

    alice_session = chat_service.create_session(db_session, alice.id, title="alice's chat")

    # Bob 不能访问 Alice 的会话
    with pytest.raises(HTTPException) as exc:
        chat_service.get_session(db_session, alice_session.session_uuid, bob.id)
    assert exc.value.status_code == 403

    # Alice 自己可以访问
    got = chat_service.get_session(db_session, alice_session.session_uuid, alice.id)
    assert got.id == alice_session.id

    # 管理员越权可访问
    got_admin = chat_service.get_session(
        db_session, alice_session.session_uuid, bob.id, is_superuser=True
    )
    assert got_admin.id == alice_session.id


def test_list_sessions_isolates_users(db_session):
    alice = _make_user(db_session, "alice")
    bob = _make_user(db_session, "bob")

    chat_service.create_session(db_session, alice.id, title="a1")
    chat_service.create_session(db_session, alice.id, title="a2")
    chat_service.create_session(db_session, bob.id, title="b1")

    alice_items, alice_total = chat_service.list_sessions(db_session, user_id=alice.id)
    assert alice_total == 2
    assert all(s.user_id == alice.id for s in alice_items)

    _, admin_total = chat_service.list_sessions(
        db_session, user_id=alice.id, is_superuser=True
    )
    assert admin_total == 3


def test_list_messages_returns_in_chronological_order(db_session):
    """默认返回全部消息，按创建时间正序"""
    user = _make_user(db_session, "alice")
    session = chat_service.create_session(db_session, user.id)

    for i in range(3):
        chat_service.append_message(
            db_session, session.session_uuid, user.id, role="user", content=f"msg-{i}"
        )

    messages = chat_service.list_messages(db_session, session.session_uuid, user.id)
    assert [m.content for m in messages] == ["msg-0", "msg-1", "msg-2"]


def test_list_messages_with_limit_keeps_time_order(db_session):
    """limit 只取最近 N 条，但返回仍按时间正序（供 Agent 拼上下文）"""
    user = _make_user(db_session, "alice")
    session = chat_service.create_session(db_session, user.id)
    for i in range(5):
        chat_service.append_message(
            db_session, session.session_uuid, user.id, role="user", content=f"msg-{i}"
        )

    recent = chat_service.list_messages(db_session, session.session_uuid, user.id, limit=3)
    assert [m.content for m in recent] == ["msg-2", "msg-3", "msg-4"]


def test_delete_session_recycles_then_purge_cascades_messages(db_session):
    """回收站期间保留消息，彻底清理后再级联删除。"""
    from app.entity.db_models import ChatMessage, ChatSession
    from app.services.resource_lifecycle_service import resource_lifecycle_service

    user = _make_user(db_session, "alice")
    session = chat_service.create_session(db_session, user.id)
    chat_service.append_message(
        db_session, session.session_uuid, user.id, role="user", content="hello"
    )
    session_id = session.id

    recycled = chat_service.delete_session(db_session, session.session_uuid, user.id)

    remaining_messages = db_session.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    ).all()
    assert len(remaining_messages) == 1
    assert recycled.deletion_status == "trashed"

    resource_lifecycle_service.purge_chat_session(db_session, recycled)
    assert db_session.query(ChatSession).filter(ChatSession.id == session_id).first() is None
    assert db_session.query(ChatMessage).filter(ChatMessage.session_id == session_id).all() == []


def test_archive_session_soft_deletes(db_session):
    user = _make_user(db_session, "alice")
    session = chat_service.create_session(db_session, user.id)
    chat_service.archive_session(db_session, session.session_uuid, user.id)

    db_session.refresh(session)
    assert session.status == "archived"

    # 归档后仍能拿到（软删除，未硬删）
    got = chat_service.get_session(db_session, session.session_uuid, user.id)
    assert got.id == session.id


def test_rename_session(db_session):
    user = _make_user(db_session, "alice")
    session = chat_service.create_session(db_session, user.id, title="old")

    updated = chat_service.rename_session(
        db_session, session.session_uuid, user.id, title="new title"
    )
    assert updated.title == "new title"


def test_get_history_returns_session_and_messages(db_session):
    user = _make_user(db_session, "alice")
    session = chat_service.create_session(db_session, user.id)
    chat_service.append_message(db_session, session.session_uuid, user.id, "user", "hi")
    chat_service.append_message(db_session, session.session_uuid, user.id, "assistant", "hello")

    s, msgs = chat_service.get_history(db_session, session.session_uuid, user.id)
    assert s.id == session.id
    assert [m.role for m in msgs] == ["user", "assistant"]


# ─────────────────────── operation_log_service ───────────────────────

def test_record_persists_audit_entry(db_session):
    user = _make_user(db_session, "alice")

    log = operation_log_service.record(
        db_session, user=user, module="auth", action="login",
        target_type="user", target_id=str(user.id),
        description="用户登录",
    )
    assert log is not None
    assert log.user_id == user.id
    assert log.username == "alice"
    assert log.module == "auth"
    assert log.action == "login"
    assert log.status == "success"


def test_record_survives_when_user_is_none(db_session):
    """系统级操作没有关联用户，也能正常记录"""
    log = operation_log_service.record(
        db_session, user=None, module="system", action="init",
        description="系统初始化",
    )
    assert log is not None
    assert log.user_id is None
    assert log.username is None


def test_record_captures_failure(db_session):
    """记录失败操作，用于后续追查异常"""
    log = operation_log_service.record(
        db_session, user=None, module="auth", action="login",
        target_type="user", target_id="mystery-user",
        description="登录失败",
        status="failure", error_message="用户名或密码错误",
    )
    assert log.status == "failure"
    assert log.error_message == "用户名或密码错误"


def test_list_logs_supports_filters(db_session):
    alice = _make_user(db_session, "alice")

    operation_log_service.record(db_session, user=alice, module="auth", action="login")
    operation_log_service.record(db_session, user=alice, module="auth", action="logout")
    operation_log_service.record(
        db_session, user=alice, module="detection", action="delete_task",
        target_type="detection_task", target_id="1",
    )

    all_items, all_total = operation_log_service.list_logs(db_session)
    assert all_total == 3

    auth_items, auth_total = operation_log_service.list_logs(db_session, module="auth")
    assert auth_total == 2
    assert all(item.module == "auth" for item in auth_items)

    login_items, login_total = operation_log_service.list_logs(db_session, action="login")
    assert login_total == 1
    assert login_items[0].action == "login"


def test_list_logs_pagination(db_session):
    alice = _make_user(db_session, "alice")
    for _ in range(5):
        operation_log_service.record(db_session, user=alice, module="auth", action="login")

    page1, total = operation_log_service.list_logs(db_session, page=1, page_size=2)
    page2, _ = operation_log_service.list_logs(db_session, page=2, page_size=2)
    page3, _ = operation_log_service.list_logs(db_session, page=3, page_size=2)

    assert total == 5
    assert len(page1) == 2
    assert len(page2) == 2
    assert len(page3) == 1


def test_log_persists_username_after_user_delete(db_session):
    """
    这是审计日志的核心价值：即使用户被删除、user_id 置 NULL，
    冗余的 username 字段仍能告诉你当时是谁操作的。
    """
    alice = _make_user(db_session, "alice")
    operation_log_service.record(db_session, user=alice, module="auth", action="login")

    # 模拟用户删除时的处理（真实代码里由 delete_user_cascade 做）
    db_session.query(OperationLog).filter(OperationLog.user_id == alice.id).update(
        {OperationLog.user_id: None}, synchronize_session=False
    )
    db_session.commit()

    log = db_session.query(OperationLog).first()
    assert log.user_id is None
    assert log.username == "alice"  # 冗余字段仍然可读


def test_record_accepts_compatibility_user_without_username(db_session):
    user = SimpleNamespace(id=77)

    log = operation_log_service.record(
        db_session, user=user, module="system", action="background_job",
    )

    assert log is not None
    assert log.user_id == 77
    assert log.username is None


def test_record_failure_never_raises(db_session, monkeypatch):
    """日志写入失败不能影响主业务：制造一个 add 异常，确认返回 None 而不是抛出"""
    def broken_add(*args, **kwargs):
        raise RuntimeError("db is on fire")

    monkeypatch.setattr(db_session, "add", broken_add)

    log = operation_log_service.record(
        db_session, user=None, module="auth", action="login",
    )
    assert log is None  # 静默失败
