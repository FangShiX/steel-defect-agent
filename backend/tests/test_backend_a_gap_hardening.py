import io
from pathlib import Path
import zipfile

import pytest
from PIL import Image


def _jpeg_bytes():
    data = io.BytesIO()
    Image.new("RGB", (16, 16), "white").save(data, format="JPEG")
    return data.getvalue()

from fastapi import HTTPException, UploadFile

from app.api import agent as agent_api
from app.api import auth as auth_api
from app.api import training as training_api
from app.entity.db_models import (
    DetectionScene,
    DetectionTask,
    Permission,
    ResourceCleanupJob,
    Role,
    RolePermission,
    TrainingDataset,
    TrainingTask,
    User,
    UserRole,
)
from app.services.authorization_service import authorization_service
from app.services.history_service import history_service
from app.services.resource_lifecycle_service import resource_lifecycle_service
from app.services.scene_service import scene_service
from app.services.training_service import training_service
from app.services.user_service import user_service


def _user(db, name, *, superuser=False):
    user = User(
        username=name,
        email=f"{name}@example.com",
        hashed_password="x",
        is_superuser=superuser,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _scene(db, name="steel"):
    scene = DetectionScene(
        name=name,
        display_name=name,
        category="industry",
        class_names=["scratch"],
    )
    db.add(scene)
    db.commit()
    db.refresh(scene)
    return scene


def test_public_task_ids_are_opaque_and_unique(db_session):
    user = _user(db_session, "alice")
    scene = _scene(db_session)
    detection = history_service.create_task(db_session, user.id, scene.id, "single")
    training = training_service.create_task(db_session, user.id, scene.id)

    assert detection.public_task_id.startswith("det_")
    assert training.public_task_id.startswith("trn_")
    assert str(detection.id) != detection.public_task_id
    assert str(training.id) != training.public_task_id


def test_detection_idempotency_rejects_duplicate_creation(db_session):
    user = _user(db_session, "alice")
    scene = _scene(db_session)
    first = history_service.create_task(
        db_session, user.id, scene.id, "single", idempotency_key="same-request"
    )

    with pytest.raises(HTTPException) as exc:
        history_service.create_task(
            db_session, user.id, scene.id, "single", idempotency_key="same-request"
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "duplicate_request"
    assert exc.value.detail["public_task_id"] == first.public_task_id
    assert db_session.query(DetectionTask).count() == 1


def test_detection_recycle_restore_and_optimistic_version(db_session):
    user = _user(db_session, "alice")
    scene = _scene(db_session)
    task = history_service.create_task(db_session, user.id, scene.id, "single")

    with pytest.raises(HTTPException) as exc:
        history_service.delete_task(
            db_session, task.id, user.id, expected_version=task.resource_version + 1
        )
    assert exc.value.status_code == 409

    trashed = history_service.delete_task(
        db_session, task.id, user.id, expected_version=task.resource_version
    )
    assert trashed.deletion_status == "trashed"
    assert trashed.purge_after is not None
    assert history_service.list_tasks(db_session, user.id)[1] == 0

    restored = history_service.restore_task(
        db_session, task.id, user.id, expected_version=trashed.resource_version
    )
    assert restored.deletion_status == "active"
    assert history_service.list_tasks(db_session, user.id)[1] == 1


def test_cleanup_failure_is_auditable_and_retryable(db_session, monkeypatch):
    user = _user(db_session, "alice")
    scene = _scene(db_session)
    task = history_service.create_task(db_session, user.id, scene.id, "single")
    history_service.add_results(db_session, task.id, [{
        "image_path": "http://minio/ssdd-images/original.jpg",
        "annotated_image_url": "http://minio/ssdd-images/annotated.jpg",
        "class_name": "scratch",
        "class_id": 0,
        "confidence": 0.9,
        "bbox": [0, 0, 10, 10],
    }])
    history_service.delete_task(db_session, task.id, user.id)

    class FailingMinio:
        def delete_by_url(self, _url, *, suppress_errors=True):
            raise RuntimeError("storage offline")

    monkeypatch.setattr(
        "app.services.resource_lifecycle_service.MinIOClient", FailingMinio
    )
    with pytest.raises(HTTPException) as exc:
        resource_lifecycle_service.purge_detection_task(db_session, task)

    assert exc.value.status_code == 502
    db_session.refresh(task)
    assert task.deletion_status == "cleanup_failed"
    job = db_session.query(ResourceCleanupJob).one()
    assert job.status == "failed"
    assert job.retry_count == 1
    assert "storage offline" in job.error_message

    class WorkingMinio:
        def delete_by_url(self, _url, *, suppress_errors=True):
            return None

    monkeypatch.setattr(
        "app.services.resource_lifecycle_service.MinIOClient", WorkingMinio
    )
    retried = resource_lifecycle_service.retry_cleanup_job(db_session, job.id)
    assert retried.id == job.id
    assert retried.status == "completed"
    assert db_session.query(DetectionTask).filter_by(id=task.id).first() is None


@pytest.mark.asyncio
async def test_same_dataset_filename_isolated_by_owner_and_uuid(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(training_api, "_dataset_root", lambda: tmp_path)
    alice = _user(db_session, "alice")
    bob = _user(db_session, "bob")

    def upload():
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w") as archive:
            archive.writestr("data.yaml", "path: .\ntrain: images/train\nval: images/val\nnames: [scratch]\n")
            archive.writestr("images/train/a.jpg", _jpeg_bytes())
            archive.writestr("images/val/b.jpg", _jpeg_bytes())
            archive.writestr("labels/train/a.txt", "0 0.5 0.5 0.2 0.2\n")
            archive.writestr("labels/val/b.txt", "0 0.5 0.5 0.2 0.2\n")
        content.seek(0)
        return UploadFile(filename="same-name.zip", file=content)

    alice_result = await training_api.upload_dataset(upload(), db=db_session, current_user=alice, dataset_format="auto", train_ratio=0.8, val_ratio=0.1, test_ratio=0.1, split_seed=42)
    bob_result = await training_api.upload_dataset(upload(), db=db_session, current_user=bob, dataset_format="auto", train_ratio=0.8, val_ratio=0.1, test_ratio=0.1, split_seed=42)

    assert alice_result["display_name"] == bob_result["display_name"] == "same-name"
    assert alice_result["storage_key"] != bob_result["storage_key"]
    assert alice_result["storage_key"].startswith(f"u{alice.id}_")
    assert bob_result["storage_key"].startswith(f"u{bob.id}_")
    assert db_session.query(TrainingDataset).count() == 2


@pytest.mark.asyncio
async def test_dataset_upload_idempotency_and_invalid_zip_compensation(
    db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(training_api, "_dataset_root", lambda: tmp_path)
    alice = _user(db_session, "alice")

    def valid_upload():
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w") as archive:
            archive.writestr("data.yaml", "path: .\ntrain: images/train\nval: images/val\nnames: [scratch]\n")
            archive.writestr("images/train/a.jpg", _jpeg_bytes())
            archive.writestr("images/val/b.jpg", _jpeg_bytes())
            archive.writestr("labels/train/a.txt", "0 0.5 0.5 0.2 0.2\n")
            archive.writestr("labels/val/b.txt", "0 0.5 0.5 0.2 0.2\n")
        content.seek(0)
        return UploadFile(filename="dataset.zip", file=content)

    first = await training_api.upload_dataset(
        valid_upload(), db=db_session, current_user=alice, idempotency_key="upload-once", dataset_format="auto", train_ratio=0.8, val_ratio=0.1, test_ratio=0.1, split_seed=42
    )
    with pytest.raises(HTTPException) as duplicate:
        await training_api.upload_dataset(
            valid_upload(), db=db_session, current_user=alice, idempotency_key="upload-once", dataset_format="auto", train_ratio=0.8, val_ratio=0.1, test_ratio=0.1, split_seed=42
        )
    assert duplicate.value.status_code == 409
    assert duplicate.value.detail["storage_key"] == first["storage_key"]

    invalid = UploadFile(filename="broken.zip", file=io.BytesIO(b"not-a-zip"))
    before = {path.name for path in tmp_path.iterdir()}
    with pytest.raises(HTTPException) as broken:
        await training_api.upload_dataset(invalid, db=db_session, current_user=alice, idempotency_key="broken", dataset_format="auto", train_ratio=0.8, val_ratio=0.1, test_ratio=0.1, split_seed=42)
    assert broken.value.status_code == 400
    assert {path.name for path in tmp_path.iterdir()} == before
    assert db_session.query(TrainingDataset).count() == 1


def test_user_cleanup_failure_keeps_user_and_retry_finishes(db_session, monkeypatch):
    alice = _user(db_session, "alice")
    scene = _scene(db_session)
    task = history_service.create_task(db_session, alice.id, scene.id, "single")
    history_service.add_results(db_session, task.id, [{
        "image_path": "http://minio/ssdd-images/original.jpg",
        "class_name": "scratch",
        "class_id": 0,
        "confidence": 0.9,
        "bbox": [0, 0, 1, 1],
    }])

    class OfflineMinio:
        def __init__(self):
            raise RuntimeError("storage offline")

    monkeypatch.setattr("app.services.user_service.MinIOClient", OfflineMinio)
    with pytest.raises(HTTPException) as failed:
        user_service.delete_user_cascade(db_session, alice.id)
    assert failed.value.status_code == 502
    assert db_session.query(User).filter_by(id=alice.id).first() is not None
    job = db_session.query(ResourceCleanupJob).filter_by(resource_type="user").one()
    assert job.status == "failed"

    class WorkingMinio:
        def delete_by_url(self, _url, *, suppress_errors=True):
            return None

    monkeypatch.setattr("app.services.user_service.MinIOClient", WorkingMinio)
    completed = resource_lifecycle_service.retry_cleanup_job(db_session, job.id)
    assert completed.status == "completed"
    assert db_session.query(User).filter_by(id=alice.id).first() is None


def test_agent_artifacts_and_upload_paths_are_owner_scoped(tmp_path, monkeypatch):
    alice = type("UserStub", (), {"id": 1, "is_superuser": False})()
    bob = type("UserStub", (), {"id": 2, "is_superuser": False})()
    monkeypatch.setattr(agent_api, "ARTIFACT_DIR", str(tmp_path))
    artifact = tmp_path / "annotated_u1_token.jpg"
    artifact.write_bytes(b"jpeg")

    from app.core.artifact_access import register_artifact, artifact_owner_id
    token = artifact_owner_id.set(alice.id)
    try:
        register_artifact(artifact.name)
    finally:
        artifact_owner_id.reset(token)
    assert Path(agent_api.get_agent_artifact(artifact.name, alice).path) == artifact
    with pytest.raises(HTTPException) as forbidden:
        agent_api.get_agent_artifact(artifact.name, bob)
    assert forbidden.value.status_code == 404


@pytest.mark.asyncio
async def test_admin_user_metadata_does_not_expose_private_content(db_session):
    admin = _user(db_session, "admin", superuser=True)
    alice = _user(db_session, "alice")
    result = await auth_api.list_users_for_admin(
        page=1, page_size=20, current_user=admin, db=db_session
    )
    item = next(value for value in result["items"] if value["id"] == alice.id)
    assert "hashed_password" not in item
    assert "password_reset_tokens" not in item
    assert "messages" not in item
    assert "attachments" not in item


def test_rbac_codes_override_legacy_superuser_flag(db_session):
    user = _user(db_session, "legacy_admin", superuser=True)
    role = Role(name="limited", display_name="limited")
    permission = Permission(code="system:audit:read", name="audit", module="system")
    db_session.add_all([role, permission])
    db_session.flush()
    db_session.add_all([
        UserRole(user_id=user.id, role_id=role.id),
        RolePermission(role_id=role.id, permission_id=permission.id),
    ])
    db_session.commit()

    assert authorization_service.has_permission(db_session, user, "system:audit:read")
    assert not authorization_service.has_permission(db_session, user, "system:user:delete")


def test_private_models_are_filtered_by_owner(db_session):
    alice = _user(db_session, "alice")
    bob = _user(db_session, "bob")
    scene = _scene(db_session)
    alice_model = scene_service.create_uploaded_model(
        db_session, scene.id, alice.id, "v1", "alice-model", "yolo11n", "models/a.pt", 1
    )
    scene_service.create_uploaded_model(
        db_session, scene.id, bob.id, "v1", "bob-model", "yolo11n", "models/b.pt", 1
    )

    visible = scene_service.list_model_versions(
        db_session, scene.id, user_id=alice.id, is_superuser=False
    )
    assert [model.id for model in visible] == [alice_model.id]


def test_private_model_recycle_restore_and_version_conflict(db_session):
    alice = _user(db_session, "alice")
    scene = _scene(db_session)
    model = scene_service.create_uploaded_model(
        db_session, scene.id, alice.id, "v1", "alice-model", "yolo11n", "models/a.pt", 1
    )

    with pytest.raises(HTTPException) as exc:
        scene_service.delete_model_version(
            db_session, scene.id, model.id, alice.id,
            expected_version=model.resource_version + 1,
        )
    assert exc.value.status_code == 409

    deleted = scene_service.delete_model_version(
        db_session, scene.id, model.id, alice.id, expected_version=model.resource_version
    )
    assert deleted.status == "deleted"
    assert deleted.purge_after is not None
    assert scene_service.list_model_versions(db_session, scene.id, alice.id) == []

    restored = scene_service.restore_model_version(
        db_session, scene.id, model.id, alice.id, expected_version=deleted.resource_version
    )
    assert restored.status == "active"
    assert restored.purge_after is None
