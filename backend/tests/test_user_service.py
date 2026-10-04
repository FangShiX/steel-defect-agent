"""用户服务测试：唯一约束、禁用登录、事务回滚、级联删除"""
import pytest
from fastapi import HTTPException

from app.entity.db_models import User, DetectionScene
from app.services.user_service import user_service


def test_register_rejects_duplicate_username(db_session):
    user_service.register(db_session, "alice", "alice@example.com", "password123")
    with pytest.raises(HTTPException) as exc:
        user_service.register(db_session, "alice", "alice2@example.com", "password123")
    assert exc.value.status_code == 400


def test_register_rejects_duplicate_email(db_session):
    user_service.register(db_session, "bob", "bob@example.com", "password123")
    with pytest.raises(HTTPException) as exc:
        user_service.register(db_session, "bob2", "bob@example.com", "password123")
    assert exc.value.status_code == 400


def test_login_wrong_password_rejected(db_session):
    user_service.register(db_session, "carol", "carol@example.com", "password123")
    with pytest.raises(HTTPException) as exc:
        user_service.login(db_session, "carol", "wrong-password")
    assert exc.value.status_code == 401


def test_disabled_user_cannot_login(db_session):
    """对应任务文档步骤 8 的验收标准：禁用用户无法登录"""
    user = user_service.register(db_session, "dave", "dave@example.com", "password123")
    user_service.set_active(db_session, user.id, is_active=False)

    with pytest.raises(HTTPException) as exc:
        user_service.login(db_session, "dave", "password123")
    assert exc.value.status_code == 403


def test_change_password_requires_correct_old_password(db_session):
    user = user_service.register(db_session, "erin", "erin@example.com", "password123")
    with pytest.raises(HTTPException):
        user_service.change_password(db_session, user, "wrong-old-password", "newpassword")

    user_service.change_password(db_session, user, "password123", "newpassword")
    # 用新密码能登录
    logged_in = user_service.login(db_session, "erin", "newpassword")
    assert logged_in.id == user.id


def test_password_reset_flow(db_session):
    user = user_service.register(db_session, "frank", "frank@example.com", "password123")
    token = user_service.request_password_reset(db_session, "frank@example.com")
    assert token is not None

    user_service.confirm_password_reset(db_session, token, "brandnewpassword")
    logged_in = user_service.login(db_session, "frank", "brandnewpassword")
    assert logged_in.id == user.id

    # 令牌用过一次后不能再用
    with pytest.raises(HTTPException):
        user_service.confirm_password_reset(db_session, token, "anotherpassword")


def test_password_reset_unknown_email_returns_none(db_session):
    token = user_service.request_password_reset(db_session, "not-registered@example.com")
    assert token is None


def test_delete_user_cascade_removes_related_rows_and_anonymizes_scenes(db_session, monkeypatch):
    """对应任务文档步骤 13：删除用户时事务化清理关联数据，场景保留但解除创建者关联"""
    # MinIO 在测试环境不可用，delete_by_url 打个桩，只验证被调用不报错
    monkeypatch.setattr(
        "app.services.user_service.MinIOClient",
        lambda: type("Stub", (), {"delete_by_url": staticmethod(lambda url, **kwargs: None)})(),
    )

    user = user_service.register(db_session, "grace", "grace@example.com", "password123")

    scene = DetectionScene(
        name="test_scene", display_name="测试场景", category="industry",
        class_names=["a", "b"], created_by=user.id,
    )
    db_session.add(scene)
    db_session.commit()

    user_service.delete_user_cascade(db_session, user.id)

    assert db_session.query(User).filter(User.id == user.id).first() is None
    # 场景本身应该保留，只是 created_by 变成 None（不是级联删除场景）
    remaining_scene = db_session.query(DetectionScene).filter(DetectionScene.id == scene.id).first()
    assert remaining_scene is not None
    assert remaining_scene.created_by is None


def test_delete_nonexistent_user_raises_404(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.services.user_service.MinIOClient",
        lambda: type("Stub", (), {"delete_by_url": staticmethod(lambda url, **kwargs: None)})(),
    )
    with pytest.raises(HTTPException) as exc:
        user_service.delete_user_cascade(db_session, 999999)
    assert exc.value.status_code == 404
