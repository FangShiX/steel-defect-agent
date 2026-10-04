"""场景与训练服务测试：唯一约束、默认模型切换事务、训练指标写入"""
import pytest
from fastapi import HTTPException

from app.entity.db_models import User
from app.services.scene_service import scene_service
from app.services.training_service import training_service
from app.services.user_service import user_service


def _make_user(db):
    user = User(username="alice", email="alice@example.com", hashed_password="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_scene_name_must_be_unique(db_session):
    scene_service.create_scene(db_session, "steel_surface_defect", "钢铁表面缺陷检测", "industry", ["crazing"])
    with pytest.raises(HTTPException) as exc:
        scene_service.create_scene(db_session, "steel_surface_defect", "重复场景", "industry", ["x"])
    assert exc.value.status_code == 400


def test_user_list_is_paginated_and_newest_first(db_session):
    _make_user(db_session)
    second = User(username="bob", email="bob@example.com", hashed_password="x")
    db_session.add(second)
    db_session.commit()

    users, total = user_service.list_users(db_session, page=1, page_size=1)

    assert total == 2
    assert [user.username for user in users] == ["bob"]


def test_admin_resource_status_is_audited_and_forbidden_to_regular_users(client, db_session):
    from app.api.auth import get_current_user
    from app.entity.db_models import DetectionTask, DetectionResult, DetectionScene, ModelVersion, OperationLog
    from main import app

    admin = User(username="resource-admin", email="resource-admin@example.com", hashed_password="x", is_superuser=True)
    regular = User(username="resource-user", email="resource-user@example.com", hashed_password="x")
    scene = DetectionScene(name="resource-scene", display_name="资源场景", category="test", class_names=["scratch"])
    db_session.add_all([admin, regular, scene])
    db_session.flush()
    model = ModelVersion(scene_id=scene.id, version="v1", model_name="resource-model", model_path="model.pt", cleanup_pending=True)
    task = DetectionTask(user_id=regular.id, scene_id=scene.id, task_type="single", status="completed")
    db_session.add_all([model, task])
    db_session.flush()
    db_session.add(DetectionResult(task_id=task.id, image_path="image.jpg", class_name="scratch", class_id=0, confidence=0.9, bbox=[0, 0, 1, 1], cleanup_pending=True))
    db_session.commit()

    app.dependency_overrides[get_current_user] = lambda: admin
    try:
        response = client.get("/api/auth/resource-status")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 200
    assert response.json()["resources"]["models"] == 1
    assert response.json()["cleanup_pending"] == {"models": 1, "detection_results": 1, "knowledge_documents": 0}
    assert db_session.query(OperationLog).filter_by(action="view_resource_status").count() == 1

    app.dependency_overrides[get_current_user] = lambda: regular
    try:
        forbidden = client.get("/api/auth/resource-status")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert forbidden.status_code == 403


def test_set_default_model_rejects_another_users_private_model(db_session):
    owner = _make_user(db_session)
    other = User(username="other", email="other@example.com", hashed_password="x")
    db_session.add(other)
    scene = scene_service.create_scene(db_session, "private_default", "Private default", "industry", ["crazing"])
    model = training_service.create_model_version(db_session, scene.id, "v1.0.0", "yolo11n", "/models/private.pt")
    model.owner_id = owner.id
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        scene_service.set_default_model(db_session, scene.id, model.id, user_id=other.id)

    assert exc.value.status_code == 404


def test_training_task_lifecycle_and_metrics(db_session):
    user = _make_user(db_session)
    scene = scene_service.create_scene(db_session, "steel_surface_defect", "钢铁表面缺陷检测", "industry", ["crazing"])

    task = training_service.create_task(db_session, user.id, scene.id, epochs=10)
    assert task.status == "pending"
    assert task.task_uuid  # 自动生成了唯一标识

    training_service.start_task(db_session, task.id)
    training_service.record_epoch_metric(db_session, task.id, epoch=1, box_loss=0.5, map50=0.3)
    training_service.record_epoch_metric(db_session, task.id, epoch=5, box_loss=0.2, map50=0.6)
    completed = training_service.complete_task(db_session, task.id)

    assert completed.status == "completed"
    assert completed.current_epoch == 5
    assert completed.progress == 100

    metrics = training_service.list_metrics(db_session, task.id)
    assert [m.epoch for m in metrics] == [1, 5]  # 按 epoch 顺序返回，用于画曲线


def test_set_default_model_swaps_atomically(db_session):
    """切换默认模型：同一场景任意时刻只能有一个默认模型"""
    user = _make_user(db_session)
    scene = scene_service.create_scene(db_session, "steel_surface_defect", "钢铁表面缺陷检测", "industry", ["crazing"])

    m1 = training_service.create_model_version(db_session, scene.id, "v1.0.0", "yolov11n", "/models/v1.pt")
    m2 = training_service.create_model_version(db_session, scene.id, "v1.1.0", "yolov11n", "/models/v2.pt")

    scene_service.set_default_model(db_session, scene.id, m1.id)
    db_session.refresh(m1)
    assert m1.is_default is True

    scene_service.set_default_model(db_session, scene.id, m2.id)
    db_session.refresh(m1)
    db_session.refresh(m2)
    assert m1.is_default is False  # 旧默认被自动取消
    assert m2.is_default is True


def test_scene_model_list_keeps_non_default_versions_visible(db_session):
    user = _make_user(db_session)
    scene = scene_service.create_scene(db_session, "visible_versions", "Visible versions", "industry", ["crazing"])
    old_model = training_service.create_model_version(db_session, scene.id, "v1.0.0", "yolo11n", "/models/v1.pt")
    current_model = training_service.create_model_version(db_session, scene.id, "v3.0.0", "yolo11n", "/models/v3.pt")
    deleted_model = training_service.create_model_version(db_session, scene.id, "v0.9.0", "yolo11n", "/models/old.pt")
    scene_service.set_default_model(db_session, scene.id, current_model.id)
    deleted_model.status = "deleted"
    db_session.commit()

    models = scene_service.list_model_versions(db_session, scene.id)

    assert [model.id for model in models] == [current_model.id, old_model.id]


def test_scene_model_list_keeps_cleanup_pending_deleted_version_visible_to_owner(db_session):
    user = _make_user(db_session)
    scene = scene_service.create_scene(db_session, "cleanup_visible", "Cleanup visible", "industry", ["crazing"])
    model = training_service.create_model_version(db_session, scene.id, "v1.0.0", "yolo11n", "/models/v1.pt")
    model.owner_id = user.id
    model.status = "deleted"
    model.cleanup_pending = True
    db_session.commit()

    models = scene_service.list_model_versions(db_session, scene.id, user.id)

    assert [item.id for item in models] == [model.id]


def test_archived_model_cannot_become_default(db_session):
    scene = scene_service.create_scene(db_session, "active_default", "Active default", "industry", ["crazing"])
    model = training_service.create_model_version(db_session, scene.id, "v1.0.0", "yolo11n", "/models/v1.pt")
    model.status = "archived"
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        scene_service.set_default_model(db_session, scene.id, model.id)

    assert exc.value.status_code == 404


def test_delete_model_version_hides_non_default_model(db_session):
    user = _make_user(db_session)
    scene = scene_service.create_scene(db_session, "deletable_model", "Deletable model", "industry", ["crazing"])
    default_model = training_service.create_model_version(db_session, scene.id, "v1.0.0", "yolo11n", "/models/v1.pt")
    other_model = training_service.create_model_version(db_session, scene.id, "v1.1.0", "yolo11n", "/models/v2.pt")
    other_model.owner_id = user.id
    db_session.commit()
    scene_service.set_default_model(db_session, scene.id, default_model.id)

    deleted = scene_service.delete_model_version(db_session, scene.id, other_model.id, user.id)

    assert deleted.status == "deleted"
    assert [model.id for model in scene_service.list_model_versions(db_session, scene.id)] == [default_model.id]


def test_delete_model_version_rejects_default_model(db_session):
    user = _make_user(db_session)
    scene = scene_service.create_scene(db_session, "protected_default", "Protected default", "industry", ["crazing"])
    model = training_service.create_model_version(db_session, scene.id, "v1.0.0", "yolo11n", "/models/v1.pt")
    model.owner_id = user.id
    db_session.commit()
    scene_service.set_default_model(db_session, scene.id, model.id)

    with pytest.raises(HTTPException) as exc:
        scene_service.delete_model_version(db_session, scene.id, model.id, user_id=user.id)

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "RESOURCE_IN_USE"


def test_model_local_cleanup_failure_is_recorded_and_retried(db_session, tmp_path, monkeypatch):
    user = _make_user(db_session)
    scene = scene_service.create_scene(db_session, "local_cleanup", "Local cleanup", "industry", ["crazing"])
    model_file = tmp_path / "model.pt"
    model_file.write_bytes(b"weights")
    model = training_service.create_model_version(db_session, scene.id, "v1.0.0", "yolo11n", str(model_file))
    model.owner_id = user.id
    db_session.commit()

    original_unlink = type(model_file).unlink
    monkeypatch.setattr(type(model_file), "unlink", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("locked")))
    with pytest.raises(HTTPException) as exc:
        scene_service.delete_model_version(db_session, scene.id, model.id, user.id)
    assert exc.value.status_code == 503
    db_session.refresh(model)
    assert model.status == "deleted"
    assert model.cleanup_pending is True
    assert "local file: locked" in model.cleanup_error

    monkeypatch.setattr(type(model_file), "unlink", original_unlink)
    cleaned = scene_service.retry_model_cleanup(db_session, scene.id, model.id, user.id)
    assert cleaned.cleanup_pending is False
    assert not model_file.exists()


def test_background_cleanup_retries_local_model_file(db_session, tmp_path):
    from app.storage.cleanup import retry_pending_cleanups

    user = _make_user(db_session)
    scene = scene_service.create_scene(db_session, "background_local_cleanup", "Background local cleanup", "industry", ["crazing"])
    model_file = tmp_path / "background-model.pt"
    model_file.write_bytes(b"weights")
    model = training_service.create_model_version(db_session, scene.id, "v1.0.0", "yolo11n", str(model_file))
    model.owner_id = user.id
    model.status = "deleted"
    model.cleanup_pending = True
    db_session.commit()

    result = retry_pending_cleanups(db_session)
    db_session.refresh(model)
    assert result["attempted"] == 1
    assert result["succeeded"] == 1
    assert model.cleanup_pending is False
    assert not model_file.exists()


def test_model_cleanup_uses_legacy_minio_url_when_object_key_is_missing(db_session, tmp_path, monkeypatch):
    user = _make_user(db_session)
    scene = scene_service.create_scene(db_session, "legacy_model_cleanup", "Legacy cleanup", "industry", ["crazing"])
    model_file = tmp_path / "legacy-model.pt"
    model_file.write_bytes(b"weights")
    model = training_service.create_model_version(db_session, scene.id, "v1.0.0", "yolo11n", str(model_file))
    model.owner_id = user.id
    model.minio_url = "http://minio.local/ssdd-images/models/legacy-model.pt"
    db_session.commit()
    deleted_urls = []

    class FakeMinIO:
        def delete_by_url(self, url):
            deleted_urls.append(url)

        def delete_file(self, _key):
            raise AssertionError("legacy record must use its URL fallback")

    monkeypatch.setattr("app.storage.minio_client.MinIOClient", FakeMinIO)

    deleted = scene_service.delete_model_version(db_session, scene.id, model.id, user.id)

    assert deleted.status == "deleted"
    assert deleted_urls == [model.minio_url]
    assert not model_file.exists()


def test_background_cleanup_retries_legacy_detection_urls(db_session, monkeypatch):
    from app.entity.db_models import DetectionResult, DetectionTask
    from app.storage.cleanup import retry_pending_cleanups

    user = _make_user(db_session)
    scene = scene_service.create_scene(db_session, "legacy_result_cleanup", "Legacy result cleanup", "industry", ["crazing"])
    task = DetectionTask(user_id=user.id, scene_id=scene.id, task_type="single", status="completed")
    db_session.add(task)
    db_session.flush()
    result = DetectionResult(
        task_id=task.id,
        image_path="http://minio.local/ssdd-images/legacy/original.jpg",
        annotated_image_url="http://minio.local/ssdd-images/legacy/annotated.jpg",
        class_name="crazing",
        class_id=0,
        confidence=0.9,
        bbox=[0, 0, 1, 1],
        cleanup_pending=True,
    )
    db_session.add(result)
    db_session.commit()
    deleted_urls = []

    class FakeMinIO:
        def delete_by_url(self, url):
            deleted_urls.append(url)

    monkeypatch.setattr("app.storage.cleanup.MinIOClient", FakeMinIO)

    retry_pending_cleanups(db_session)

    assert deleted_urls == [result.image_path, result.annotated_image_url]
    assert db_session.get(DetectionTask, task.id) is None


def test_training_task_rejects_unknown_scene(db_session):
    user = _make_user(db_session)
    with pytest.raises(HTTPException) as exc:
        training_service.create_task(db_session, user.id, scene_id=999999)
    assert exc.value.status_code == 404
