"""
知识库服务测试：权限边界（用户隔离 / 系统文档可见性 / 管理员越权访问）

不覆盖 add_chunks / search_similar_chunks：knowledge_chunks 表用了 pgvector 的
Vector 类型，SQLite 测试库里没建这张表（见 conftest.py），向量检索需要连真实
PostgreSQL + pgvector 才能测，这里只测文档级别的增删查权限。
"""
import asyncio
import io

import pytest
from fastapi import HTTPException
from fastapi import UploadFile

from app.entity.db_models import User
from app.api import knowledge
from app.services.knowledge_service import knowledge_service


def _make_user(db, username, is_superuser=False):
    user = User(
        username=username, email=f"{username}@example.com",
        hashed_password="x", is_superuser=is_superuser,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_doc(db, user_id, title="doc"):
    return knowledge_service.create_document(
        db, user_id=user_id, title=title, filename=f"{title}.txt",
        file_url=f"http://minio/knowledge/{title}.txt", file_type="txt",
    )


def test_owner_can_read_and_admin_sees_all(db_session):
    alice = _make_user(db_session, "alice")
    bob = _make_user(db_session, "bob")
    admin = _make_user(db_session, "admin", is_superuser=True)

    alice_doc = _make_doc(db_session, alice.id, "alice-doc")
    _make_doc(db_session, bob.id, "bob-doc")
    system_doc = _make_doc(db_session, None, "system-doc")

    # 非管理员只能看到：自己的 + 系统内置的，看不到别人的私有文档
    alice_visible = knowledge_service.list_documents(db_session, user_id=alice.id, is_superuser=False)
    assert {d.title for d in alice_visible} == {"alice-doc", "system-doc"}

    # 管理员能看到全部
    admin_visible = knowledge_service.list_documents(db_session, user_id=admin.id, is_superuser=True)
    assert {d.title for d in admin_visible} == {"alice-doc", "bob-doc", "system-doc"}

    # get_document：越权访问别人的私有文档要 403，系统文档任何登录用户都能读
    with pytest.raises(HTTPException) as exc:
        knowledge_service.get_document(db_session, alice_doc.id, user_id=bob.id, is_superuser=False)
    assert exc.value.status_code == 403

    got = knowledge_service.get_document(db_session, system_doc.id, user_id=bob.id, is_superuser=False)
    assert got.title == "system-doc"


def test_delete_permission_boundary(db_session):
    alice = _make_user(db_session, "alice")
    bob = _make_user(db_session, "bob")
    admin = _make_user(db_session, "admin", is_superuser=True)

    alice_doc = _make_doc(db_session, alice.id, "alice-doc")
    system_doc = _make_doc(db_session, None, "system-doc")

    # bob 删不了 alice 的文档
    with pytest.raises(HTTPException) as exc:
        knowledge_service.delete_document(db_session, alice_doc.id, user_id=bob.id, is_superuser=False)
    assert exc.value.status_code == 403

    # 普通用户删不了系统内置文档
    with pytest.raises(HTTPException) as exc:
        knowledge_service.delete_document(db_session, system_doc.id, user_id=alice.id, is_superuser=False)
    assert exc.value.status_code == 403

    # 本人可以删自己的文档
    knowledge_service.delete_document(db_session, alice_doc.id, user_id=alice.id, is_superuser=False)
    with pytest.raises(HTTPException) as exc:
        knowledge_service.get_document(db_session, alice_doc.id, user_id=alice.id, is_superuser=False)
    assert exc.value.status_code == 404

    # 管理员可以删系统文档
    knowledge_service.delete_document(db_session, system_doc.id, user_id=admin.id, is_superuser=True)


def test_delete_nonexistent_document_raises_404(db_session):
    alice = _make_user(db_session, "alice")
    with pytest.raises(HTTPException) as exc:
        knowledge_service.delete_document(db_session, 9999, user_id=alice.id, is_superuser=False)
    assert exc.value.status_code == 404


def test_download_requires_document_visibility_and_uses_object_key(db_session, monkeypatch):
    alice = _make_user(db_session, "download-alice")
    bob = _make_user(db_session, "download-bob")
    doc = _make_doc(db_session, alice.id, "download-doc")
    doc.object_key = "knowledge/alice/download-doc.txt"
    db_session.commit()
    monkeypatch.setattr(
        knowledge, "MinIOClient",
        lambda: type("Stub", (), {"get_presigned_url": staticmethod(lambda key: f"http://minio/{key}")})(),
    )
    monkeypatch.setattr(
        "app.services.knowledge_service.MinIOClient",
        lambda: type("Stub", (), {"get_presigned_url": staticmethod(lambda key: f"http://minio/{key}")})(),
    )

    response = knowledge.download_document(doc.id, current_user=alice, db=db_session)
    assert response.status_code == 307
    assert response.headers["location"].endswith(doc.object_key)
    with pytest.raises(HTTPException) as exc:
        knowledge.download_document(doc.id, current_user=bob, db=db_session)
    assert exc.value.status_code == 403


def test_upload_compensates_minio_object_when_document_insert_fails(db_session, monkeypatch):
    user = _make_user(db_session, "upload-compensation")
    deleted = []
    stub = type("Stub", (), {
        "upload_bytes": staticmethod(lambda *_args: "http://minio/knowledge/upload.txt"),
        "delete_file": staticmethod(lambda key: deleted.append(key)),
    })()
    monkeypatch.setattr(knowledge, "MinIOClient", lambda: stub)
    monkeypatch.setattr(
        knowledge.knowledge_service,
        "create_document",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )
    upload = UploadFile(filename="upload.txt", file=io.BytesIO(b"content"), headers={"content-type": "text/plain"})

    with pytest.raises(RuntimeError, match="database unavailable"):
        asyncio.run(knowledge.upload_document(upload, title=None, is_system=False, current_user=user, db=db_session))
    assert len(deleted) == 1
    assert deleted[0].startswith("knowledge/")
