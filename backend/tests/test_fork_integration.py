"""Regression checks for local file ledger + upstream/PR lifecycle coexistence."""
from collections import Counter

import pytest
from fastapi import HTTPException

from app.api.auth import get_current_user
from app.entity.db_models import ChatMessage, ChatSession, StoredFile, User
from app.services.file_service import file_service
from app.services.user_service import user_service
from main import app


@pytest.fixture
def memory_storage(monkeypatch):
    class Storage:
        objects = {}
        fail_delete = False

        def upload_bytes(self, key, data, _content_type):
            self.objects[key] = data

        def get_presigned_url(self, key):
            return f"https://storage.example/{key}"

        def delete_file(self, key):
            if self.fail_delete:
                raise RuntimeError("storage unavailable")
            self.objects.pop(key, None)

        def delete_by_url(self, url, **_kwargs):
            self.delete_file(url.split("storage.example/", 1)[-1])

    storage = Storage()
    for module in ("app.services.file_service", "app.api.files", "app.services.user_service"):
        monkeypatch.setattr(f"{module}.MinIOClient", lambda: storage)
    return storage


def make_user(db, name):
    user = User(username=name, email=f"{name}@example.com", hashed_password="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_file_api_upload_archive_restore_and_cross_user_access(client, db_session, memory_storage):
    alice = make_user(db_session, "file-owner")
    bob = make_user(db_session, "file-visitor")
    app.dependency_overrides[get_current_user] = lambda: alice
    response = client.post("/api/files", files={"file": ("sample.txt", b"data", "text/plain")})
    assert response.status_code == 201, response.text
    item = response.json()
    assert memory_storage.objects[item["object_key"]] == b"data"
    assert client.post(f"/api/files/{item['id']}/archive").json()["status"] == "archived"
    assert client.post(f"/api/files/{item['id']}/restore").json()["status"] == "active"
    app.dependency_overrides[get_current_user] = lambda: bob
    assert client.get(f"/api/files/{item['id']}").status_code == 403
    assert client.delete(f"/api/files/{item['id']}").status_code == 403
    assert client.get("/api/files").json() == []
    app.dependency_overrides[get_current_user] = lambda: alice
    assert client.delete(f"/api/files/{item['id']}").json()["status"] == "deleted"
    assert not memory_storage.objects


def test_pending_file_cleanup_cannot_be_restored(db_session, memory_storage):
    user = make_user(db_session, "cleanup-owner")
    item = file_service.create(db_session, user.id, "sample.txt", "text/plain", b"data")
    memory_storage.fail_delete = True
    item = file_service.delete(db_session, item.id, user.id, False)
    assert item.status == "cleanup_pending"
    with pytest.raises(HTTPException) as exc:
        file_service.update_status(db_session, item.id, user.id, False, "active")
    assert exc.value.status_code == 409
    memory_storage.fail_delete = False
    assert file_service.delete(db_session, item.id, user.id, False).status == "deleted"


def test_user_cascade_cleans_local_file_ledger(db_session, memory_storage):
    user = make_user(db_session, "cascade-owner")
    file_service.create(db_session, user.id, "sample.txt", "text/plain", b"data")
    user_service.delete_user_cascade(db_session, user.id)
    assert db_session.query(StoredFile).count() == 0
    assert db_session.query(User).count() == 0
    assert not memory_storage.objects


def test_chat_trash_restore_keeps_messages(client, db_session):
    user = make_user(db_session, "trash-owner")
    session = ChatSession(user_id=user.id, session_uuid="fork-integration-session")
    db_session.add(session)
    db_session.flush()
    db_session.add(ChatMessage(session_id=session.id, role="user", content="keep this"))
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: user
    assert client.post(f"/api/agent/sessions/{session.session_uuid}/trash").status_code == 200
    assert client.get(f"/api/chat/sessions/{session.session_uuid}").status_code == 404
    assert db_session.query(ChatMessage).count() == 1
    assert client.post(f"/api/chat/sessions/{session.session_uuid}/restore").status_code == 200
    assert client.get(f"/api/chat/sessions/{session.session_uuid}").status_code == 200


def test_no_duplicate_http_routes():
    counts = Counter(
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", ())
        if route.path.startswith("/api/")
    )
    assert {route: count for route, count in counts.items() if count > 1} == {}


def test_chat_purge_cleans_video_attachment_and_artifact(db_session, tmp_path, monkeypatch):
    from app.api import agent
    from app.services.chat_service import chat_service
    from app.services.resource_lifecycle_service import resource_lifecycle_service

    user = make_user(db_session, "video-cleanup-owner")
    monkeypatch.setattr(agent, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(agent, "ARTIFACT_DIR", str(tmp_path / "artifacts"))
    attachment = tmp_path / "uploads" / str(user.id) / "video.mp4"
    attachment.parent.mkdir(parents=True)
    attachment.write_bytes(b"video")
    artifact = tmp_path / "artifacts" / "annotated_cleanup.jpg"
    artifact.parent.mkdir()
    artifact.write_bytes(b"jpeg")
    session = ChatSession(user_id=user.id, session_uuid="video-cleanup-session")
    db_session.add(session)
    db_session.flush()
    db_session.add(ChatMessage(
        session_id=session.id, role="user", content="video",
        attachments=[{"path": str(attachment), "content_type": "video/mp4"}],
        tool_calls=[{"result": {"image_url": f"/api/agent/artifacts/{artifact.name}"}}],
    ))
    db_session.commit()
    chat_service.delete_session(db_session, session.session_uuid, user.id)
    assert attachment.is_file() and artifact.is_file()
    resource_lifecycle_service.purge_chat_session(db_session, session)
    assert not attachment.exists() and not artifact.exists()
