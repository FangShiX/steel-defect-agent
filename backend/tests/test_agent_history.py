import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.api import agent
from app.agent.detection_agent import make_detection_tools
from app.core.artifact_access import artifact_owner_id, can_read_artifact, register_artifact
from app.entity.db_models import ChatMessage, ChatSession, User
from app.services.action_confirmation_service import action_confirmation_service


def _confirm_delete_chat_session(db_session, user_id, session_id):
    item = action_confirmation_service.prepare(
        db_session, user_id=user_id, operation="delete_chat_session",
        target_type="chat_session", target_id=session_id,
        impact={"scope": "conversation messages, attachments, and generated artifacts", "reversible": False},
        payload={"session_id": session_id},
    )
    action_confirmation_service.confirm(db_session, item.confirmation_uuid, user_id)
    return item.confirmation_uuid


def test_history_restores_the_original_image_path_for_agent_context(db_session, monkeypatch):
    user = User(username="chat-image", email="chat-image@example.com", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    session = ChatSession(user_id=user.id, session_uuid="session-with-image")
    db_session.add(session)
    db_session.flush()

    image_path = agent._user_upload_dir(user.id) / "history-context-test.jpg"
    image_path.write_bytes(b"image")
    db_session.add_all([
        ChatMessage(session_id=session.id, role="user", content="请分析这张图", image_path=str(image_path)),
        ChatMessage(session_id=session.id, role="assistant", content="已收到图片"),
    ])
    db_session.commit()
    monkeypatch.setattr(agent, "SessionLocal", sessionmaker(bind=db_session.get_bind()))

    history = agent._load_history(session.session_uuid, user.id)

    assert history[0]["role"] == "user"
    assert "请分析这张图" in history[0]["content"]
    assert f"[附件图片路径: {image_path}" in history[0]["content"]
    assert history[1] == {"role": "assistant", "content": "已收到图片"}
    image_path.unlink(missing_ok=True)


def test_uploaded_image_path_is_isolated_by_user(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "UPLOAD_DIR", str(tmp_path))
    owner_path = agent._new_upload_path(101, ".jpg")
    owner_path.write_bytes(b"image")

    assert agent._validate_uploaded_image_path(str(owner_path), user_id=101) == str(owner_path.resolve())
    with pytest.raises(HTTPException) as exc:
        agent._validate_uploaded_image_path(str(owner_path), user_id=202)
    assert exc.value.status_code == 403


def test_detection_agent_registers_video_tool():
    tools = make_detection_tools(101)

    assert "detect_video_file" in {item.name for item in tools}


def test_chat_stream_rejects_another_users_uploaded_image(client):
    def register_and_login(username):
        client.post("/api/auth/register", json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "password123",
        })
        response = client.post("/api/auth/login", json={"username": username, "password": "password123"})
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    alice_headers = register_and_login("image-owner")
    bob_headers = register_and_login("image-visitor")
    upload = client.post(
        "/api/agent/upload",
        headers=alice_headers,
        files={"file": ("sample.jpg", b"image-bytes", "image/jpeg")},
    )
    assert upload.status_code == 200

    response = client.post(
        "/api/agent/chat/stream",
        headers=bob_headers,
        json={"message": "分析图片", "image_path": upload.json()["image_path"]},
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "HTTP_403"


def test_save_message_keeps_image_only_user_messages(db_session, monkeypatch, tmp_path):
    user = User(username="image-only", email="image-only@example.com", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    session = ChatSession(user_id=user.id, session_uuid="image-only-session")
    db_session.add(session)
    db_session.flush()

    image_path = tmp_path / "image-only.jpg"
    image_path.write_bytes(b"image")
    monkeypatch.setattr(agent, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    agent._save_message(session.session_uuid, user.id, "user", "", image_path=str(image_path))

    saved = db_session.query(ChatMessage).filter_by(session_id=session.id).one()
    db_session.refresh(session)
    assert saved.content == ""
    assert saved.image_path == str(image_path)
    assert session.message_count == 1
    assert session.title == "图片消息"


def test_chat_stream_initializes_image_path_for_text_only_requests(db_session, monkeypatch):
    """Text-only requests must reach the history save path without NameError."""
    captured = {}

    async def fake_chat_stream(**kwargs):
        yield {"type": "text_chunk", "content": "收到"}

    monkeypatch.setattr(agent.supervisor_agent, "chat_stream", fake_chat_stream)
    monkeypatch.setattr(agent, "_load_history", lambda *_args: [])
    monkeypatch.setattr(
        agent,
        "_save_message",
        lambda *args, **kwargs: captured.setdefault("calls", []).append((args, kwargs)),
    )

    class User:
        id = 7

    class Request:
        headers = {"content-type": "application/json"}

        async def json(self):
            return {"message": "你好", "session_id": "text-only"}

    import asyncio

    response = asyncio.run(agent.chat_stream(Request(), _current_user=User(), db=db_session))
    asyncio.run(_consume(response.body_iterator))
    assert captured["calls"][0][1]["image_path"] is None


def test_chat_stream_passes_json_model_to_supervisor(db_session, monkeypatch):
    captured = {}

    async def fake_chat_stream(**kwargs):
        captured.update(kwargs)
        yield {"type": "text_chunk", "content": "收到"}

    monkeypatch.setattr(agent.supervisor_agent, "chat_stream", fake_chat_stream)
    monkeypatch.setattr(agent, "_load_history", lambda *_args: [])
    monkeypatch.setattr(agent, "_save_message", lambda *args, **kwargs: None)

    class User:
        id = 7

    class Request:
        headers = {"content-type": "application/json"}

        async def json(self):
            return {"message": "你好", "session_id": "json-model", "model": "qwen-plus-latest"}

    response = asyncio.run(agent.chat_stream(Request(), _current_user=User(), db=db_session))
    asyncio.run(_consume(response.body_iterator))

    assert captured["model"] == "qwen-plus-latest"


def test_chat_stream_persists_partial_reply_when_cancelled(db_session, monkeypatch):
    captured = []

    async def fake_chat_stream(**_kwargs):
        yield {"type": "text_chunk", "content": "部分回复"}
        raise asyncio.CancelledError()

    monkeypatch.setattr(agent.supervisor_agent, "chat_stream", fake_chat_stream)
    monkeypatch.setattr(agent, "_load_history", lambda *_args: [])
    monkeypatch.setattr(agent, "_save_message", lambda *args, **kwargs: captured.append((args, kwargs)))

    class User:
        id = 7

    class Request:
        headers = {"content-type": "application/json"}

        async def json(self):
            return {"message": "你好", "session_id": "cancelled-session"}

    response = asyncio.run(agent.chat_stream(Request(), _current_user=User(), db=db_session))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_consume(response.body_iterator))

    assert [call[0][2] for call in captured] == ["user", "assistant"]
    assert captured[1][0][3] == "部分回复"


async def _consume(iterator):
    async for _ in iterator:
        pass


def test_delete_chat_session_moves_persisted_messages_to_recycle_bin(db_session):
    user = User(
        username="delete-chat", email="delete-chat@example.com", hashed_password="x"
    )
    db_session.add(user)
    db_session.flush()
    session = ChatSession(user_id=user.id, session_uuid="delete-chat-session")
    db_session.add(session)
    db_session.flush()
    db_session.add(ChatMessage(session_id=session.id, role="user", content="delete me"))
    db_session.commit()

    confirmation_id = _confirm_delete_chat_session(db_session, user.id, session.session_uuid)
    result = agent.trash_chat_session(
        session.session_uuid, current_user=user, db=db_session,
    )

    assert result["id"] == session.session_uuid
    recycled = db_session.query(ChatSession).filter_by(id=session.id).one()
    assert recycled.deletion_status == "trashed"
    assert db_session.query(ChatMessage).filter_by(session_id=session.id).count() == 1


def test_delete_chat_session_removes_its_attachment_and_artifact(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(agent, "ARTIFACT_DIR", str(tmp_path / "artifacts"))
    user = User(username="delete-assets", email="delete-assets@example.com", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    session = ChatSession(user_id=user.id, session_uuid="delete-assets-session")
    db_session.add(session)
    db_session.flush()
    attachment = agent._new_upload_path(user.id, ".png")
    attachment.write_bytes(b"image")
    artifact_dir = Path(agent.ARTIFACT_DIR)
    artifact_dir.mkdir(parents=True)
    artifact_name = "annotated_delete-assets.jpg"
    artifact = artifact_dir / artifact_name
    artifact.write_bytes(b"image")
    owner_token = artifact_owner_id.set(user.id)
    try:
        register_artifact(artifact_name)
    finally:
        artifact_owner_id.reset(owner_token)
    db_session.add(ChatMessage(
        session_id=session.id,
        role="assistant",
        content="done",
        image_path=str(attachment),
        image_paths=[str(attachment)],
        tool_calls=[{"payload": {"result": {"annotated_image_url": f"/api/agent/artifacts/{artifact_name}"}}}],
    ))
    db_session.commit()

    confirmation_id = _confirm_delete_chat_session(db_session, user.id, session.session_uuid)
    agent.delete_chat_session(
        session.session_uuid, confirmation_id=confirmation_id,
        current_user=user, db=db_session,
    )

    assert not attachment.exists()
    assert not artifact.exists()
    assert not can_read_artifact(artifact_name, user.id)


def test_saved_assistant_message_keeps_agent_tool_trace(db_session, monkeypatch):
    user = User(username="tool-trace", email="tool-trace@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    monkeypatch.setattr(agent, "SessionLocal", sessionmaker(bind=db_session.get_bind()))

    agent._save_message(
        "tool-trace-session", user.id, "assistant", "done",
        tool_calls=[{"name": "detect_single_image", "status": "success", "result": "{}"}],
    )

    saved = db_session.query(ChatMessage).one()
    assert saved.tool_calls == [{"name": "detect_single_image", "status": "success", "result": "{}"}]


def test_agent_card_trace_has_stable_type_order_and_references(db_session, monkeypatch):
    user = User(username="card-trace", email="card-trace@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    monkeypatch.setattr(agent, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    result = {"task_id": 12, "model_id": 8, "detections": []}
    trace = {
        "id": "trace-1",
        "name": "detect_single_image",
        "status": "success",
        "card_type": agent._card_type_for_tool("detect_single_image"),
        "display_order": 0,
        "payload": result,
        "references": agent._card_references(result),
        "snapshot": {"tool": "detect_single_image"},
    }

    agent._save_message("card-trace-session", user.id, "assistant", "", tool_calls=[trace])

    saved = db_session.query(ChatMessage).one()
    assert saved.tool_calls[0]["card_type"] == "detection_result"
    assert saved.tool_calls[0]["display_order"] == 0
    assert saved.tool_calls[0]["references"] == {"task_ids": [12], "model_ids": [8]}


def test_agent_artifact_is_only_visible_to_its_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "ARTIFACT_DIR", str(tmp_path))
    artifact = tmp_path / "annotated_owner-only.jpg"
    artifact.write_bytes(b"image")
    token = artifact_owner_id.set(7)
    try:
        register_artifact(artifact.name)
    finally:
        artifact_owner_id.reset(token)

    owner = type("User", (), {"id": 7, "is_superuser": False})()
    other = type("User", (), {"id": 8, "is_superuser": False})()
    assert Path(agent.get_agent_artifact(artifact.name, current_user=owner).path) == artifact
    with pytest.raises(HTTPException) as exc_info:
        agent.get_agent_artifact(artifact.name, current_user=other)
    assert exc_info.value.status_code == 404


def test_persisted_agent_artifact_is_visible_after_registry_reset(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "ARTIFACT_DIR", str(tmp_path))
    user = User(username="artifact-history", email="artifact-history@example.com", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    session = ChatSession(user_id=user.id, session_uuid="artifact-history-session")
    db_session.add(session)
    db_session.flush()
    artifact_name = "annotated_persisted.jpg"
    (tmp_path / artifact_name).write_bytes(b"image")
    db_session.add(ChatMessage(
        session_id=session.id,
        role="assistant",
        content="done",
        tool_calls=[{"result": {"annotated_image_url": f"/api/agent/artifacts/{artifact_name}"}}],
    ))
    db_session.commit()

    owner = type("User", (), {"id": user.id, "is_superuser": False})()
    assert agent._artifact_referenced_by_user(db_session, artifact_name, owner)
    assert Path(agent.get_agent_artifact(artifact_name, current_user=owner, db=db_session).path).exists()


def test_save_message_rejects_session_uuid_owned_by_another_user(db_session, monkeypatch):
    owner = User(username="session-owner", email="owner@example.com", hashed_password="x")
    other = User(username="session-other", email="other@example.com", hashed_password="x")
    db_session.add_all([owner, other])
    db_session.flush()
    db_session.add(ChatSession(user_id=owner.id, session_uuid="shared-session-uuid"))
    db_session.commit()
    monkeypatch.setattr(agent, "SessionLocal", sessionmaker(bind=db_session.get_bind()))

    with pytest.raises(HTTPException) as exc_info:
        agent._save_message("shared-session-uuid", other.id, "user", "不能接管")

    assert exc_info.value.status_code == 409
    assert db_session.query(ChatSession).count() == 1
    assert db_session.query(ChatMessage).count() == 0


def test_chat_stream_rejects_foreign_session_before_streaming(db_session):
    owner = User(username="stream-owner", email="stream-owner@example.com", hashed_password="x")
    other = User(username="stream-other", email="stream-other@example.com", hashed_password="x")
    db_session.add_all([owner, other])
    db_session.flush()
    db_session.add(ChatSession(user_id=owner.id, session_uuid="foreign-stream-session"))
    db_session.commit()

    class Request:
        headers = {"content-type": "application/json"}

        async def json(self):
            return {"message": "你好", "session_id": "foreign-stream-session"}

    import asyncio

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(agent.chat_stream(Request(), _current_user=other, db=db_session))

    assert exc_info.value.status_code == 409


def test_admin_can_list_and_read_other_users_sessions(db_session):
    admin = User(
        username="chat-admin", email="chat-admin@example.com", hashed_password="x",
        is_superuser=True,
    )
    owner = User(username="chat-owner", email="chat-owner@example.com", hashed_password="x")
    db_session.add_all([admin, owner])
    db_session.flush()
    session = ChatSession(user_id=owner.id, session_uuid="admin-visible-session", title="用户会话")
    db_session.add(session)
    db_session.flush()
    db_session.add(ChatMessage(session_id=session.id, role="user", content="仅用于管理员查看"))
    db_session.commit()

    sessions = agent.list_chat_sessions(current_user=admin, db=db_session)
    detail = agent.get_chat_session(session.session_uuid, current_user=admin, db=db_session)

    assert sessions[0]["owner_id"] == owner.id
    assert sessions[0]["owner_username"] == owner.username
    assert detail["owner_username"] == owner.username
    assert detail["messages"][0]["content"] == "仅用于管理员查看"


def test_owner_can_update_session_metadata_and_list_filters(db_session):
    owner = User(username="session-owner", email="session-owner@example.com", hashed_password="x")
    db_session.add(owner)
    db_session.flush()
    session = ChatSession(user_id=owner.id, session_uuid="editable-session", title="Old title")
    db_session.add(session)
    db_session.commit()

    updated = agent.update_chat_session(
        session.session_uuid,
        agent.AgentSessionUpdate(title="Renamed", archived=True),
        current_user=owner,
        db=db_session,
    )
    assert updated["title"] == "Renamed"
    assert updated["archived"] is True
    listing = agent.list_chat_sessions(current_user=owner, db=db_session, archived=True, page=1, page_size=20)
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == session.session_uuid


def test_admin_cannot_delete_other_users_session(db_session):
    admin = User(
        username="delete-admin", email="delete-admin@example.com", hashed_password="x",
        is_superuser=True,
    )
    owner = User(username="delete-owner", email="delete-owner@example.com", hashed_password="x")
    db_session.add_all([admin, owner])
    db_session.flush()
    db_session.add(ChatSession(user_id=owner.id, session_uuid="protected-session"))
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        agent.delete_chat_session("protected-session", current_user=admin, db=db_session)

    assert exc_info.value.status_code == 409
    assert db_session.query(ChatSession).count() == 1


def test_regular_user_cannot_read_other_users_session(db_session):
    owner = User(username="private-owner", email="private-owner@example.com", hashed_password="x")
    other = User(username="private-other", email="private-other@example.com", hashed_password="x")
    db_session.add_all([owner, other])
    db_session.flush()
    db_session.add(ChatSession(user_id=owner.id, session_uuid="private-session"))
    db_session.commit()

    assert agent.list_chat_sessions(current_user=other, db=db_session) == []
    with pytest.raises(HTTPException) as exc_info:
        agent.get_chat_session("private-session", current_user=other, db=db_session)

    assert exc_info.value.status_code == 404
