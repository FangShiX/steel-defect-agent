import json
from io import BytesIO
from pathlib import Path
import zipfile

import pytest
import yaml
from PIL import Image

from app.training.dataset_importer import DatasetImportError, detect_format, import_dataset
from app.api.auth import get_current_user
from app.config.settings import settings
from app.entity.db_models import TrainingDataset, User
from main import app


def _image(path: Path, size=(100, 80)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color=(20, 30, 40)).save(path)


def _image_bytes(size=(100, 80)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color=(20, 30, 40)).save(output, format="JPEG")
    return output.getvalue()


def test_voc_discovery_uses_annotation_reference_not_directory_names(tmp_path):
    source = tmp_path / "source"
    image = source / "totally" / "unknown" / "pixels" / "sample.jpg"
    annotation = source / "another" / "place" / "record.xml"
    _image(image)
    annotation.parent.mkdir(parents=True)
    annotation.write_text(
        """<annotation><filename>sample.jpg</filename><size><width>100</width><height>80</height></size>
        <object><name>surface_defect</name><bndbox><xmin>10</xmin><ymin>20</ymin><xmax>50</xmax><ymax>60</ymax></bndbox></object></annotation>""",
        encoding="utf-8",
    )

    target = tmp_path / "normalized"
    report = import_dataset(source, target, "auto", (0.8, 0.2, 0), seed=7)

    assert report["source_format"] == "voc"
    assert report["classes"] == ["surface_defect"]
    assert report["images"] == report["boxes"] == 1
    assert next((target / "labels").rglob("sample.txt")).read_text() == "0 0.300000 0.500000 0.400000 0.500000"


def test_voc_discovery_rejects_ambiguous_same_name_images(tmp_path):
    source = tmp_path / "source"
    _image(source / "a" / "same.jpg")
    _image(source / "b" / "same.jpg")
    xml = source / "meta" / "one.xml"
    xml.parent.mkdir()
    xml.write_text("<annotation><filename>same.jpg</filename></annotation>", encoding="utf-8")

    with pytest.raises(DatasetImportError) as exc:
        import_dataset(source, tmp_path / "out", "voc")

    assert exc.value.code == "AMBIGUOUS_IMAGE"
    assert len(exc.value.details["candidates"]) == 2


def test_annotation_reference_cannot_escape_upload_root(tmp_path):
    outside = tmp_path / "outside.jpg"
    _image(outside)
    source = tmp_path / "source"
    source.mkdir()
    _image(source / "unrelated.jpg")
    (source / "record.xml").write_text(
        f"<annotation><path>{outside}</path><object><name>x</name></object></annotation>",
        encoding="utf-8",
    )

    with pytest.raises(DatasetImportError) as exc:
        import_dataset(source, tmp_path / "out", "voc")

    assert exc.value.code == "MISSING_IMAGE"


def test_coco_content_detection_and_conversion(tmp_path):
    source = tmp_path / "source"
    _image(source / "assets" / "one.png", (200, 100))
    metadata = source / "metadata.bin.json"
    metadata.write_text(json.dumps({
        "images": [{"id": 9, "file_name": "one.png", "width": 200, "height": 100}],
        "categories": [{"id": 12, "name": "scratch"}],
        "annotations": [{"id": 1, "image_id": 9, "category_id": 12, "bbox": [20, 10, 40, 20]}],
    }), encoding="utf-8")

    assert detect_format(source) == "coco"
    report = import_dataset(source, tmp_path / "out", "auto", (0.8, 0.2, 0))
    assert report["classes"] == ["scratch"]
    assert next((tmp_path / "out" / "labels").rglob("one.txt")).read_text() == "0 0.200000 0.200000 0.200000 0.200000"


def test_labelme_polygon_becomes_detection_bounding_box(tmp_path):
    source = tmp_path / "source"
    _image(source / "raw" / "part.bmp", (100, 100))
    metadata = source / "labels" / "shape.json"
    metadata.parent.mkdir(parents=True)
    metadata.write_text(json.dumps({
        "imagePath": "part.bmp",
        "imageWidth": 100,
        "imageHeight": 100,
        "shapes": [{"label": "pit", "shape_type": "polygon", "points": [[10, 20], [50, 30], [20, 70]]}],
    }), encoding="utf-8")

    report = import_dataset(source, tmp_path / "out", "labelme", (0.8, 0.2, 0))
    assert report["boxes"] == 1
    assert next((tmp_path / "out" / "labels").rglob("part.txt")).read_text() == "0 0.300000 0.450000 0.400000 0.500000"


def test_yolo_paths_are_resolved_from_yaml_references_not_folder_roles(tmp_path):
    source = tmp_path / "source"
    for split in ("alpha", "beta"):
        _image(source / split / "pixels" / f"{split}.jpg")
        labels = source / split / "labels"
        labels.mkdir(parents=True)
        (labels / f"{split}.txt").write_text("0 0.5 0.5 0.2 0.2", encoding="utf-8")
    (source / "data.yaml").write_text(
        "train: ../alpha/pixels\nval: ../beta/pixels\nnc: 1\nnames: [defect]\n",
        encoding="utf-8",
    )

    target = tmp_path / "out"
    report = import_dataset(source, target, "yolo")
    config = yaml.safe_load((target / "data.yaml").read_text())

    assert report["images"] == 2
    assert config["train"] == "images/train"
    assert config["val"] == "images/val"
    assert (target / "labels" / "train" / "alpha.txt").is_file()


def test_hash_split_is_repeatable_without_using_directory_names(tmp_path):
    source = tmp_path / "source"
    annotations = source / "records"
    annotations.mkdir(parents=True)
    for number in range(30):
        name = f"image-{number}.jpg"
        _image(source / "arbitrary" / name)
        (annotations / f"record-{number}.xml").write_text(
            f"<annotation><filename>{name}</filename><object><name>x</name><bndbox><xmin>1</xmin><ymin>1</ymin><xmax>5</xmax><ymax>5</ymax></bndbox></object></annotation>",
            encoding="utf-8",
        )

    first = import_dataset(source, tmp_path / "first", "voc", (0.7, 0.2, 0.1), 123)
    second = import_dataset(source, tmp_path / "second", "voc", (0.7, 0.2, 0.1), 123)

    assert first["splits"] == second["splits"]
    for split in ("train", "val", "test"):
        assert sorted(p.name for p in (tmp_path / "first" / "images" / split).glob("*")) == sorted(
            p.name for p in (tmp_path / "second" / "images" / split).glob("*")
        )
    config = yaml.safe_load((tmp_path / "first" / "data.yaml").read_text())
    assert config["names"] == {0: "x"}


def test_upload_api_converts_voc_and_returns_report(client, db_session, tmp_path, monkeypatch):
    user = User(username="dataset-owner", email="dataset@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr(settings, "DATASET_BASE_DIR", str(tmp_path))
    archive_data = BytesIO()
    with zipfile.ZipFile(archive_data, "w") as archive:
        archive.writestr("odd/a/picture.jpg", _image_bytes())
        archive.writestr(
            "elsewhere/annotation.xml",
            "<annotation><filename>picture.jpg</filename><object><name>scratch</name>"
            "<bndbox><xmin>1</xmin><ymin>2</ymin><xmax>20</xmax><ymax>30</ymax></bndbox>"
            "</object></annotation>",
        )
    try:
        response = client.post(
            "/api/training/datasets/upload",
            files={"file": ("content-driven.zip", archive_data.getvalue(), "application/zip")},
            data={"dataset_format": "voc", "train_ratio": "0.8", "val_ratio": "0.2", "test_ratio": "0"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["conversion"]["source_format"] == "voc"
    assert body["conversion"]["classes"] == ["scratch"]
    assert (tmp_path / body["storage_key"] / "data.yaml").is_file()
    assert db_session.query(TrainingDataset).filter_by(path=body["storage_key"]).one().owner_id == user.id


def test_upload_api_rolls_back_invalid_split(client, db_session, tmp_path, monkeypatch):
    user = User(username="bad-split-owner", email="bad-split@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr(settings, "DATASET_BASE_DIR", str(tmp_path))
    archive_data = BytesIO()
    with zipfile.ZipFile(archive_data, "w") as archive:
        archive.writestr("x.jpg", _image_bytes())
        archive.writestr(
            "x.xml",
            "<annotation><filename>x.jpg</filename><object><name>x</name>"
            "<bndbox><xmin>1</xmin><ymin>1</ymin><xmax>5</xmax><ymax>5</ymax></bndbox>"
            "</object></annotation>",
        )
    try:
        response = client.post(
            "/api/training/datasets/upload",
            files={"file": ("bad-ratios.zip", archive_data.getvalue(), "application/zip")},
            data={"dataset_format": "voc", "train_ratio": "0.8", "val_ratio": "0.8", "test_ratio": "0"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_SPLIT"
    assert not (tmp_path / "bad-ratios").exists()
    assert not list(tmp_path.glob(".dataset-upload-*"))
