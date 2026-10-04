from io import BytesIO
from pathlib import Path
import zipfile

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.training import _is_builtin_dataset, _is_builtin_dataset_path, _validate_dataset_archive, _validate_dataset_classes
from app.entity.db_models import TrainingDataset
from app.entity.schemas import TrainingTaskCreate
from app.training.training_service import _create_runtime_data_yaml
from app.training.training_service import training_service


def _archive(entries):
    data = BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    data.seek(0)
    return data


def test_dataset_archive_and_classes_accept_valid_yolo_content(tmp_path):
    archive_data = _archive({
        "data.yaml": "nc: 2\nnames: [crazing, scratches]\n",
        "images/train/a.jpg": b"image-a",
        "labels/train/a.txt": "1 0.5 0.5 0.1 0.1\n",
    })
    with zipfile.ZipFile(archive_data) as archive:
        _validate_dataset_archive(archive)
        archive.extractall(tmp_path)
    _validate_dataset_classes(tmp_path)


def test_dataset_archive_accepts_duplicate_image_content_at_different_paths():
    archive_data = _archive({
        "data.yaml": "names: [crazing]\n",
        "images/a.jpg": b"same-image",
        "images/b.jpg": b"same-image",
    })
    with zipfile.ZipFile(archive_data) as archive:
        _validate_dataset_archive(archive)


def test_dataset_archive_accepts_identical_repeated_zip_member():
    data = BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("data.yaml", "names: [crazing]\n")
        archive.writestr("data.yaml", "names: [crazing]\n")
        archive.writestr("images/a.jpg", b"image-a")
    data.seek(0)
    with zipfile.ZipFile(data) as archive:
        _validate_dataset_archive(archive)


def test_dataset_archive_rejects_conflicting_repeated_zip_member():
    data = BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("data.yaml", "names: [crazing]\n")
        archive.writestr("data.yaml", "names: [scratches]\n")
        archive.writestr("images/a.jpg", b"image-a")
    data.seek(0)
    with zipfile.ZipFile(data) as archive:
        with pytest.raises(HTTPException) as exc:
            _validate_dataset_archive(archive)
    assert exc.value.detail["code"] == "DUPLICATE_CONTENT"


def test_dataset_classes_reject_out_of_range_label(tmp_path):
    (tmp_path / "labels" / "train").mkdir(parents=True)
    (tmp_path / "data.yaml").write_text("nc: 1\nnames: [crazing]\n", encoding="utf-8")
    (tmp_path / "labels" / "train" / "bad.txt").write_text("2 0.5 0.5 0.1 0.1\n", encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        _validate_dataset_classes(Path(tmp_path))
    assert exc.value.detail["code"] == "INVALID_DATASET"


@pytest.mark.parametrize("label", ["0 nan 0.5 0.1 0.1\n", "0 1.1 0.5 0.1 0.1\n", "0 0.5 0.5 0 0.1\n"])
def test_dataset_classes_reject_non_finite_or_invalid_yolo_coordinates(tmp_path, label):
    (tmp_path / "labels" / "train").mkdir(parents=True)
    (tmp_path / "data.yaml").write_text("nc: 1\nnames: [crazing]\n", encoding="utf-8")
    (tmp_path / "labels" / "train" / "bad.txt").write_text(label, encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        _validate_dataset_classes(Path(tmp_path))
    assert exc.value.detail["code"] == "INVALID_DATASET"


def test_runtime_training_yaml_uses_dataset_root_without_mutating_source(tmp_path):
    source = tmp_path / "data.yaml"
    original = "path: your-absolute-path\ntrain: images/train\nval: images/val\nnames: [crazing]\n"
    source.write_text(original, encoding="utf-8")

    runtime_path = Path(_create_runtime_data_yaml(str(source)))
    try:
        runtime = runtime_path.read_text(encoding="utf-8")
        assert f"path: {tmp_path.as_posix()}" in runtime.replace("\\", "/")
        assert source.read_text(encoding="utf-8") == original
    finally:
        runtime_path.unlink(missing_ok=True)


def test_every_dataset_marked_builtin_is_read_only():
    assert _is_builtin_dataset(TrainingDataset(path="another-shipped-dataset", is_builtin=True))
    assert _is_builtin_dataset_path("NEU-DET.v9i.yolov11")
    assert _is_builtin_dataset_path(".")


def test_training_defaults_to_cpu_when_device_is_omitted():
    assert TrainingTaskCreate(scene_id=1).device == "cpu"


def test_advanced_training_config_accepts_cloud_script_options():
    request = TrainingTaskCreate(
        scene_id=1,
        train_config={
            "mosaic": 0.8,
            "mixup": 0.1,
            "fliplr": 0.4,
            "scale": 0.3,
            "cos_lr": True,
            "erasing": 0.0,
            "label_smoothing": 0.1,
            "dropout": 0.1,
        },
    )

    assert request.train_config.scale == 0.3
    assert request.train_config.cos_lr is True
    assert request.train_config.label_smoothing == 0.1


def test_advanced_training_config_rejects_unknown_or_out_of_range_options():
    with pytest.raises(ValidationError):
        TrainingTaskCreate(scene_id=1, train_config={"project": "/tmp/override"})
    with pytest.raises(ValidationError):
        TrainingTaskCreate(scene_id=1, train_config={"mosaic": 1.1})
    with pytest.raises(ValidationError):
        training_service.start_training(None, 1, 1, {"train_config": {"project": "/tmp/override"}})
