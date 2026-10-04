from pathlib import Path

import pytest

from app.config.settings import settings
from app.entity.db_models import DetectionScene, TrainingMetric, TrainingTask, User
from app.training.training_service import (
    TrainingCancelled,
    TrainingService,
    _ensure_training_not_cancelled,
    _running_lock,
    _stop_requested,
)


def _task(db_session, task_uuid="live1234", epochs=10):
    user = User(username="monitor", email="monitor@example.com", hashed_password="x")
    scene = DetectionScene(
        name="monitor_scene", display_name="Monitor", category="industry",
        class_names=["crazing"], class_names_cn={"crazing": "裂纹"},
    )
    db_session.add_all([user, scene])
    db_session.flush()
    task = TrainingTask(
        user_id=user.id, scene_id=scene.id, task_uuid=task_uuid,
        status="running", epochs=epochs, current_epoch=0, progress=0,
    )
    db_session.add(task)
    db_session.commit()
    return task


def test_status_syncs_completed_epochs_from_results_csv(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "TRAIN_OUTPUT_DIR", str(tmp_path))
    task = _task(db_session)
    output = tmp_path / f"task_{task.task_uuid}"
    output.mkdir()
    (output / "results.csv").write_text(
        "epoch,train/box_loss,metrics/mAP50(B)\n0,0.8,0.2\n1,0.6,0.4\n",
        encoding="utf-8",
    )

    status = TrainingService.get_training_status(db_session, task.id)

    assert status["task"]["current_epoch"] == 2
    assert status["task"]["progress"] == 20
    assert status["latest_metric"]["epoch"] == 2
    assert status["latest_metric"]["map50"] == 0.4


def test_csv_sync_updates_callback_placeholder_without_duplicate(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "TRAIN_OUTPUT_DIR", str(tmp_path))
    task = _task(db_session, task_uuid="repair12")
    db_session.add(TrainingMetric(task_id=task.id, epoch=1, map50=0.0))
    db_session.commit()
    output = tmp_path / f"task_{task.task_uuid}"
    output.mkdir()
    (output / "results.csv").write_text(
        "epoch,metrics/mAP50(B)\n0,0.55\n", encoding="utf-8"
    )

    metrics = TrainingService.get_training_metrics(db_session, task.id)

    assert len(metrics) == 1
    assert metrics[0]["epoch"] == 1
    assert metrics[0]["map50"] == 0.55


def test_csv_sync_does_not_report_stale_database_epoch(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "TRAIN_OUTPUT_DIR", str(tmp_path))
    task = _task(db_session, task_uuid="stale123", epochs=10)
    db_session.add(TrainingMetric(task_id=task.id, epoch=10, map50=0.9))
    db_session.commit()
    output = tmp_path / f"task_{task.task_uuid}"
    output.mkdir()
    (output / "results.csv").write_text(
        "epoch,metrics/mAP50(B)\n0,0.2\n1,0.4\n", encoding="utf-8"
    )

    status = TrainingService.get_training_status(db_session, task.id)

    assert status["task"]["current_epoch"] == 2
    assert status["task"]["progress"] == 20
    assert status["latest_metric"]["epoch"] == 2


def test_one_based_ultralytics_csv_does_not_create_epoch_n_plus_one(tmp_path):
    csv_path = tmp_path / "results.csv"
    csv_path.write_text("epoch,metrics/mAP50(B)\n1,0.2\n2,0.4\n", encoding="utf-8")

    metrics = TrainingService.parse_results_csv(str(csv_path))

    assert [metric["epoch"] for metric in metrics] == [1, 2]


def test_batch_guard_raises_for_in_process_stop_request(db_session):
    task = _task(db_session, task_uuid="stopmem1")
    with _running_lock:
        _stop_requested.add(task.task_uuid)
    try:
        with pytest.raises(TrainingCancelled):
            _ensure_training_not_cancelled(db_session, task, task.task_uuid)
    finally:
        with _running_lock:
            _stop_requested.discard(task.task_uuid)


def test_batch_guard_raises_for_durable_cancelled_status(db_session):
    task = _task(db_session, task_uuid="stopdb12")
    task.status = "cancelled"
    db_session.commit()

    with pytest.raises(TrainingCancelled):
        _ensure_training_not_cancelled(db_session, task, task.task_uuid)


def test_stop_training_is_idempotent_and_records_stop_request(db_session):
    task = _task(db_session, task_uuid="stopapi1")
    try:
        first = TrainingService.stop_training(db_session, task.id)
        second = TrainingService.stop_training(db_session, task.id)
        db_session.refresh(task)

        assert first["task_id"] == task.id
        assert second["task_id"] == task.id
        assert task.status == "cancelled"
        with _running_lock:
            assert task.task_uuid in _stop_requested
    finally:
        with _running_lock:
            _stop_requested.discard(task.task_uuid)


def test_stop_training_cancels_pending_task_idempotently(db_session):
    task = _task(db_session, task_uuid="pending-stop")
    task.status = "pending"
    db_session.commit()

    first = TrainingService.stop_training(db_session, task.id)
    second = TrainingService.stop_training(db_session, task.id)

    assert first["task_id"] == task.id
    assert second["task_id"] == task.id
    assert db_session.get(TrainingTask, task.id).status == "cancelled"
