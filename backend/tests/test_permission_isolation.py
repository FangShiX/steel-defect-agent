"""
权限边界隔离测试
对应分工文档任务 2 的要求：
"确保用户和系统权限隔离、不同用户不能看到彼此不该看到的数据"

测试策略：造两个普通用户 alice 和 bob，各自建资源，然后交叉查询。
断言 bob 用自己的身份查 alice 的资源全部返回 403 或 404；断言管理员可以
越权查看所有人的资源；断言普通用户操作自己的资源正常。

这个测试文件跑通就等于给分工文档"权限隔离"这一条要求出了一份验收报告。
"""
import pytest
from fastapi import HTTPException

from app.entity.db_models import User, DetectionScene, DetectionTask
from app.services.chat_service import chat_service
from app.services.history_service import history_service
from app.services.training_service import training_service


# ── 测试夹具 ────────────────────────────────────────────────

def _make_user(db, username, is_superuser=False):
    user = User(
        username=username,
        email=f"{username}@example.com",
        hashed_password="dummy-hash",
        is_superuser=is_superuser,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_scene(db, created_by=None):
    scene = DetectionScene(
        name="test_scene",
        display_name="测试场景",
        category="industry",
        class_names=["a", "b"],
        created_by=created_by,
    )
    db.add(scene)
    db.commit()
    db.refresh(scene)
    return scene


@pytest.fixture
def alice(db_session):
    return _make_user(db_session, "alice")


@pytest.fixture
def bob(db_session):
    return _make_user(db_session, "bob")


@pytest.fixture
def admin(db_session):
    return _make_user(db_session, "admin", is_superuser=True)


@pytest.fixture
def scene(db_session, admin):
    return _make_scene(db_session, created_by=admin.id)


# ══════════════════════════════════════════════════════════════
# 检测历史：detection_tasks / detection_results
# ══════════════════════════════════════════════════════════════

def test_history_bob_cannot_see_alice_task_in_list(db_session, alice, bob, scene):
    """列表查询：bob 只能看到自己的检测任务，看不到 alice 的"""
    history_service.create_task(db_session, alice.id, scene.id, task_type="single")
    history_service.create_task(db_session, bob.id, scene.id, task_type="single")

    bob_items, bob_total = history_service.list_tasks(
        db_session, user_id=bob.id, is_superuser=False
    )
    assert bob_total == 1
    assert all(t.user_id == bob.id for t in bob_items)


def test_history_bob_cannot_read_alice_task_detail(db_session, alice, bob, scene):
    """详情查询：bob 直接用 task_id 访问 alice 的任务，应该 403"""
    alice_task = history_service.create_task(db_session, alice.id, scene.id, task_type="single")

    with pytest.raises(HTTPException) as exc:
        history_service.get_task_detail(
            db_session, alice_task.id, user_id=bob.id, is_superuser=False
        )
    assert exc.value.status_code == 403


def test_history_bob_cannot_delete_alice_task(db_session, alice, bob, scene):
    """删除操作：bob 尝试删 alice 的检测任务，应该 403"""
    alice_task = history_service.create_task(db_session, alice.id, scene.id, task_type="single")

    with pytest.raises(HTTPException) as exc:
        history_service.delete_task(
            db_session, alice_task.id, user_id=bob.id, is_superuser=False
        )
    assert exc.value.status_code == 403

    # 任务应该仍然存在，未被删除
    assert db_session.query(DetectionTask).filter(DetectionTask.id == alice_task.id).first() is not None


def test_history_admin_can_see_all_users(db_session, alice, bob, admin, scene):
    """管理员可以看到所有人的检测任务"""
    history_service.create_task(db_session, alice.id, scene.id, task_type="single")
    history_service.create_task(db_session, bob.id, scene.id, task_type="single")

    _, total = history_service.list_tasks(
        db_session, user_id=admin.id, is_superuser=True
    )
    assert total == 2


def test_history_owner_can_operate_own_task(db_session, alice, scene):
    """本人访问/删除自己的任务应该正常"""
    task = history_service.create_task(db_session, alice.id, scene.id, task_type="single")

    # 查详情
    detail = history_service.get_task_detail(
        db_session, task.id, user_id=alice.id, is_superuser=False
    )
    assert detail.id == task.id

    # 删任务
    deleted = history_service.delete_task(
        db_session, task.id, user_id=alice.id, is_superuser=False
    )
    assert deleted.deletion_status == "trashed"
    assert history_service.list_tasks(db_session, user_id=alice.id)[1] == 0


# ══════════════════════════════════════════════════════════════
# 统计数据：get_statistics
# ══════════════════════════════════════════════════════════════

def test_statistics_bob_only_counts_own_tasks(db_session, alice, bob, scene):
    """看板统计：bob 看到的数字里不应该包含 alice 的数据"""
    for _ in range(3):
        t = history_service.create_task(db_session, alice.id, scene.id, task_type="single")
        history_service.mark_completed(db_session, t.id, total_images=1, total_objects=5, total_inference_time=100)

    t = history_service.create_task(db_session, bob.id, scene.id, task_type="single")
    history_service.mark_completed(db_session, t.id, total_images=1, total_objects=2, total_inference_time=80)

    bob_stats = history_service.get_statistics(db_session, user_id=bob.id, is_superuser=False)
    assert bob_stats["total_tasks"] == 1  # 只有自己那一条
    assert bob_stats["total_objects"] == 2  # 不包含 alice 的 15

    admin_stats = history_service.get_statistics(db_session, user_id=bob.id, is_superuser=True)
    assert admin_stats["total_tasks"] == 4
    assert admin_stats["total_objects"] == 17  # alice 15 + bob 2


# ══════════════════════════════════════════════════════════════
# 训练任务：training_tasks
# ══════════════════════════════════════════════════════════════

def test_training_bob_cannot_see_alice_tasks_in_list(db_session, alice, bob, scene):
    training_service.create_task(db_session, alice.id, scene.id)
    training_service.create_task(db_session, bob.id, scene.id)

    bob_items = training_service.list_tasks_by_user(db_session, bob.id, is_superuser=False)
    assert len(bob_items) == 1
    assert all(t.user_id == bob.id for t in bob_items)


def test_training_admin_sees_all(db_session, alice, bob, admin, scene):
    training_service.create_task(db_session, alice.id, scene.id)
    training_service.create_task(db_session, bob.id, scene.id)

    admin_items = training_service.list_tasks_by_user(db_session, admin.id, is_superuser=True)
    assert len(admin_items) == 2


# ══════════════════════════════════════════════════════════════
# 对话历史：chat_sessions / chat_messages
# ══════════════════════════════════════════════════════════════

def test_chat_bob_cannot_access_alice_session(db_session, alice, bob):
    """bob 直接拿 alice 的 session_uuid 试图访问，应该 403"""
    alice_session = chat_service.create_session(db_session, alice.id, title="alice's chat")

    with pytest.raises(HTTPException) as exc:
        chat_service.get_session(db_session, alice_session.session_uuid, user_id=bob.id)
    assert exc.value.status_code == 403


def test_chat_bob_cannot_list_alice_sessions(db_session, alice, bob):
    """列表查询：会话列表只包含自己的"""
    chat_service.create_session(db_session, alice.id)
    chat_service.create_session(db_session, alice.id)
    chat_service.create_session(db_session, bob.id)

    bob_items, bob_total = chat_service.list_sessions(db_session, user_id=bob.id)
    assert bob_total == 1
    assert all(s.user_id == bob.id for s in bob_items)


def test_chat_bob_cannot_read_alice_messages(db_session, alice, bob):
    """消息查询：bob 拿 alice 的会话 UUID 想读消息，应该 403"""
    alice_session = chat_service.create_session(db_session, alice.id)
    chat_service.append_message(
        db_session, alice_session.session_uuid, alice.id, "user", "私密内容"
    )

    with pytest.raises(HTTPException) as exc:
        chat_service.list_messages(db_session, alice_session.session_uuid, user_id=bob.id)
    assert exc.value.status_code == 403


def test_chat_bob_cannot_delete_alice_session(db_session, alice, bob):
    alice_session = chat_service.create_session(db_session, alice.id)
    uuid = alice_session.session_uuid

    with pytest.raises(HTTPException) as exc:
        chat_service.delete_session(db_session, uuid, user_id=bob.id)
    assert exc.value.status_code == 403

    # 会话应该仍然存在
    from app.entity.db_models import ChatSession
    assert db_session.query(ChatSession).filter(ChatSession.session_uuid == uuid).first() is not None


def test_chat_admin_can_access_any_session(db_session, alice, admin):
    alice_session = chat_service.create_session(db_session, alice.id, title="alice's chat")

    got = chat_service.get_session(
        db_session, alice_session.session_uuid, user_id=admin.id, is_superuser=True
    )
    assert got.id == alice_session.id


# ══════════════════════════════════════════════════════════════
# 权限传递：owner 授权后仍然能操作自己的资源
# ══════════════════════════════════════════════════════════════

def test_alice_can_do_everything_on_own_chat(db_session, alice):
    """完整的自主 CRUD：alice 对自己的会话可以增删改查所有操作"""
    session = chat_service.create_session(db_session, alice.id, title="my chat")
    uuid = session.session_uuid

    # 追加消息
    msg = chat_service.append_message(db_session, uuid, alice.id, "user", "hello")
    assert msg.session_id == session.id

    # 读取历史
    _, messages = chat_service.get_history(db_session, uuid, alice.id)
    assert len(messages) == 1

    # 重命名
    renamed = chat_service.rename_session(db_session, uuid, alice.id, title="new title")
    assert renamed.title == "new title"

    # 归档
    archived = chat_service.archive_session(db_session, uuid, alice.id)
    assert archived.status == "archived"

    # 硬删除
    chat_service.delete_session(db_session, uuid, alice.id)


# ══════════════════════════════════════════════════════════════
# 边界：不存在的资源应该返回 404 而不是 500
# ══════════════════════════════════════════════════════════════

def test_history_nonexistent_task_returns_404(db_session, alice):
    with pytest.raises(HTTPException) as exc:
        history_service.get_task_detail(db_session, task_id=999999, user_id=alice.id)
    assert exc.value.status_code == 404


def test_chat_nonexistent_session_returns_404(db_session, alice):
    with pytest.raises(HTTPException) as exc:
        chat_service.get_session(db_session, "non-existent-uuid", user_id=alice.id)
    assert exc.value.status_code == 404
