"""YOLO 单图、批量检测服务测试。"""

import base64
import base64
import io
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image

from app.entity.db_models import DetectionScene, DetectionTask, ModelVersion, User
from app.config.detection import ALLOWED_IMAGE_TYPES
from app.services.detection_service import DetectionService


def _image_upload(filename="sample.jpg", content_type="image/jpeg", color="white"):
    output = io.BytesIO()
    Image.new("RGB", (32, 24), color).save(output, format="JPEG")
    return UploadFile(filename=filename, file=io.BytesIO(output.getvalue()), headers={"content-type": content_type})


def _seed_detection_data(db_session, model_path):
    user = User(username="detector", email="detector@example.com", hashed_password="x")
    scene = DetectionScene(
        name="steel_surface_defect",
        display_name="钢铁表面缺陷检测",
        category="industry",
        class_names=["crazing", "scratches"],
        class_names_cn={"crazing": "裂纹", "scratches": "划痕"},
    )
    db_session.add_all([user, scene])
    db_session.flush()
    model = ModelVersion(
        scene_id=scene.id,
        owner_id=user.id,
        version="v1.0.0",
        model_name="ssdd_yolo11n_v1",
        model_type="yolo11n",
        model_path=str(model_path),
        is_default=True,
        is_builtin=True,
    )
    db_session.add(model)
    db_session.commit()
    return user, model


class _FakeTensor:
    def __init__(self, value):
        self.value = value

    def item(self):
        return self.value

    def __getitem__(self, _index):
        return self

    def tolist(self):
        return self.value


class _FakeResult:
    names = {0: "crazing", 1: "scratches"}
    boxes = [
        SimpleNamespace(
            cls=_FakeTensor(1),
            conf=_FakeTensor(0.91),
            xyxy=_FakeTensor([1.0, 2.0, 20.0, 16.0]),
        )
    ]

    @staticmethod
    def plot():
        pytest.importorskip("numpy")
        import numpy as np

        return np.zeros((24, 32, 3), dtype=np.uint8)


class _FakeModel:
    def predict(self, **_kwargs):
        return [_FakeResult()]


class _FakeMinIO:
    def __init__(self):
        self.uploaded = []
        self.deleted = []

    def upload_bytes(self, object_name, data, content_type):
        self.uploaded.append((object_name, data, content_type))
        return f"http://minio/ssdd-images/{object_name}"

    def upload_file(self, object_name, file_path):
        self.uploaded.append((object_name, file_path, "video/mp4"))
        return f"http://minio/ssdd-images/{object_name}"

    def delete_by_url(self, url):
        self.deleted.append(url)


@pytest.mark.asyncio
async def test_single_detection_persists_result(db_session, tmp_path, monkeypatch):
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"weights")
    user, model_version = _seed_detection_data(db_session, weights)
    minio = _FakeMinIO()
    service = DetectionService()
    monkeypatch.setattr(service, "_get_model", lambda _version: _FakeModel())
    monkeypatch.setattr("app.services.detection_service.MinIOClient", lambda: minio)

    response = await service.detect_single(
        db_session, user.id, _image_upload(), model_version.id, 0.25, 0.45
    )

    assert response["status"] == "completed"
    assert response["total_objects"] == 1
    assert response["objects"][0]["class_name_cn"] == "划痕"
    assert len(minio.uploaded) == 2
    task = db_session.query(DetectionTask).filter_by(id=response["task_id"]).one()
    assert task.status == "completed"
    assert task.total_images == 1
    assert task.results[0].bbox == [1.0, 2.0, 20.0, 16.0]


@pytest.mark.asyncio
async def test_single_detection_marks_invalid_image_failed(db_session, tmp_path, monkeypatch):
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"weights")
    user, model_version = _seed_detection_data(db_session, weights)
    service = DetectionService()
    monkeypatch.setattr(service, "_get_model", lambda _version: _FakeModel())
    monkeypatch.setattr("app.services.detection_service.MinIOClient", _FakeMinIO)
    upload = UploadFile(
        filename="broken.jpg",
        file=io.BytesIO(b"not-an-image"),
        headers={"content-type": "image/jpeg"},
    )

    with pytest.raises(HTTPException, match="图片内容无法解析"):
        await service.detect_single(db_session, user.id, upload, model_version.id, 0.25, 0.45)

    task = db_session.query(DetectionTask).one()
    assert task.status == "failed"
    assert task.error_message == "图片内容无法解析"


@pytest.mark.asyncio
async def test_batch_detection_keeps_partial_success(db_session, tmp_path, monkeypatch):
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"weights")
    user, model_version = _seed_detection_data(db_session, weights)
    service = DetectionService()
    monkeypatch.setattr(service, "_get_model", lambda _version: _FakeModel())
    monkeypatch.setattr("app.services.detection_service.MinIOClient", _FakeMinIO)
    broken = UploadFile(
        filename="broken.txt",
        file=io.BytesIO(b"bad"),
        headers={"content-type": "text/plain"},
    )

    response = await service.detect_batch(
        db_session,
        user.id,
        [_image_upload("ok.jpg"), broken],
        model_version.id,
        0.25,
        0.45,
    )

    assert response["success_count"] == 1
    assert response["failed_count"] == 1
    assert response["items"][0]["status"] == "completed"
    assert response["items"][1]["status"] == "failed"
    task = db_session.query(DetectionTask).one()
    assert task.status == "completed"
    assert task.total_images == 2
    assert task.total_objects == 1


def test_model_path_must_exist(tmp_path):
    with pytest.raises(HTTPException, match="模型权重不存在") as exc_info:
        DetectionService._resolve_model_path(str(tmp_path / "missing.pt"))
    assert str(tmp_path) not in str(exc_info.value.detail)


def test_video_detection_samples_frames_and_persists_results(db_session, tmp_path, monkeypatch):
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    weights = tmp_path / "model.pt"
    weights.write_bytes(b"weights")
    user, model_version = _seed_detection_data(db_session, weights)
    task = DetectionTask(
        user_id=user.id,
        scene_id=model_version.scene_id,
        model_version_id=model_version.id,
        task_type="video",
        status="processing",
        conf_threshold=0.25,
        iou_threshold=0.45,
        image_size=640,
    )
    db_session.add(task)
    db_session.commit()

    video_path = tmp_path / "sample.mp4"
    writer = cv2.VideoWriter(
        str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (32, 24)
    )
    assert writer.isOpened()
    for index in range(12):
        writer.write(np.full((24, 32, 3), index * 10, dtype=np.uint8))
    writer.release()

    service = DetectionService()
    monkeypatch.setattr(service, "_get_model", lambda _version: _FakeModel())
    monkeypatch.setattr("app.services.detection_service.SessionLocal", lambda: db_session)
    monkeypatch.setattr("app.services.detection_service.MinIOClient", _FakeMinIO)
    progress = []

    result = service.detect_video(
        video_path,
        model_version.id,
        task.id,
        frame_sample_rate=3,
        max_frames=3,
        progress_callback=lambda current, total: progress.append((current, total)),
    )

    assert result["processed_frames"] == 3
    assert result["model"]["name"] == "ssdd_yolo11n_v1"
    assert result["model"]["path"] == str(weights)
    assert result["total_objects"] == 1
    assert result["class_counts"] == {"scratches": 1}
    assert result["video_resolution"] == {"width": 32, "height": 24}
    assert result["annotated_video_url"].endswith("annotated_video.mp4")
    assert len(result["key_frames"]) == 3
    assert progress[-1][0] == 12
    db_session.expire_all()
    completed = db_session.query(DetectionTask).filter_by(id=task.id).one()
    assert completed.status == "completed"
    assert len(completed.results) == 1


def test_video_tracks_match_each_detection_only_once():
    service = DetectionService()
    tracks = []
    active_tracks = []
    first_frame = [
        {"class_id": 1, "class_name": "scratches", "class_name_cn": "划痕", "confidence": 0.8,
         "bbox": [0.0, 0.0, 10.0, 10.0]},
        {"class_id": 1, "class_name": "scratches", "class_name_cn": "划痕", "confidence": 0.7,
         "bbox": [20.0, 0.0, 30.0, 10.0]},
    ]
    second_frame = [
        {"class_id": 1, "class_name": "scratches", "class_name_cn": "划痕", "confidence": 0.9,
         "bbox": [1.0, 0.0, 11.0, 10.0]},
        {"class_id": 1, "class_name": "scratches", "class_name_cn": "划痕", "confidence": 0.75,
         "bbox": [21.0, 0.0, 31.0, 10.0]},
    ]

    service._update_video_tracks(tracks, active_tracks, first_frame, 0, 5.0, 32, 24)
    service._update_video_tracks(tracks, active_tracks, second_frame, 5, 6.0, 32, 24)

    assert len(tracks) == 2
    assert [track["result"]["confidence"] for track in tracks] == [0.9, 0.75]
    assert tracks[0]["result"]["image_path"] == "frame_5.jpg"


def test_video_tracks_keep_different_classes_and_positions_separate():
    service = DetectionService()
    tracks = []
    active_tracks = []
    service._update_video_tracks(
        tracks,
        active_tracks,
        [{"class_id": 1, "class_name": "scratches", "class_name_cn": "划痕", "confidence": 0.8,
          "bbox": [0.0, 0.0, 10.0, 10.0]}],
        0, 5.0, 100, 100,
    )
    service._update_video_tracks(
        tracks,
        active_tracks,
        [
            {"class_id": 0, "class_name": "crazing", "class_name_cn": "裂纹", "confidence": 0.9,
             "bbox": [0.0, 0.0, 10.0, 10.0]},
            {"class_id": 1, "class_name": "scratches", "class_name_cn": "划痕", "confidence": 0.9,
             "bbox": [50.0, 50.0, 60.0, 60.0]},
        ],
        5, 6.0, 100, 100,
    )

    assert len(tracks) == 3


def test_video_tracks_reset_after_scene_cut():
    service = DetectionService()
    tracks = []
    active_tracks = []
    detection = {
        "class_id": 1,
        "class_name": "scratches",
        "class_name_cn": "划痕",
        "confidence": 0.8,
        "bbox": [0.0, 0.0, 10.0, 10.0],
    }

    service._update_video_tracks(tracks, active_tracks, [detection], 0, 5.0, 32, 24)
    service._update_video_tracks(
        tracks, active_tracks, [detection], 5, 5.0, 32, 24, reset=True
    )

    assert len(tracks) == 2


def test_camera_frame_returns_annotated_image(tmp_path, monkeypatch):
    pytest.importorskip("cv2")
    import numpy as np

    service = DetectionService()
    model_path = tmp_path / "model.pt"
    model_path.write_bytes(b"weights")
    scene = SimpleNamespace(class_names_cn={"scratches": "划痕"})
    model_version = SimpleNamespace(
        id=1,
        model_name="ssdd_yolo11n_v1",
        model_path=str(model_path),
        scene=scene,
    )
    monkeypatch.setattr(service, "_predict_frame", lambda *_args: [_FakeResult()])

    result = service.detect_camera_frame(
        model_version, _FakeModel(), np.zeros((24, 32, 3), dtype=np.uint8),
        "cpu", 0.25, 0.45,
    )

    assert result["object_count"] == 1
    assert result["model_id"] == 1
    assert result["model_name"] == "ssdd_yolo11n_v1"
    assert result["detections"][0]["class_name_cn"] == "划痕"
    assert base64.b64decode(result["annotated_frame"])


@pytest.mark.asyncio
async def test_zip_detection_reuses_batch_pipeline(db_session, tmp_path, monkeypatch):
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"weights")
    user, model_version = _seed_detection_data(db_session, weights)
    zip_path = tmp_path / "images.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for filename, color in (("a.jpg", "white"), ("nested/b.jpg", "gray")):
            output = io.BytesIO()
            Image.new("RGB", (32, 24), color).save(output, format="JPEG")
            archive.writestr(filename, output.getvalue())

    service = DetectionService()
    monkeypatch.setattr(service, "_get_model", lambda _version: _FakeModel())
    monkeypatch.setattr("app.services.detection_service.MinIOClient", _FakeMinIO)

    response = await service.detect_zip(
        db_session,
        user.id,
        zip_path,
        model_version.id,
        0.25,
        0.45,
        "images.zip",
    )

    assert response["source"] == "zip"
    assert response["zip_filename"] == "images.zip"
    assert response["total_images_in_zip"] == 2
    assert response["success_count"] == 2
    assert all(item["annotated_image_url"] for item in response["items"])
    task = db_session.query(DetectionTask).one()
    assert task.task_type == "zip"
    assert task.total_images == 2


def test_zip_rejects_path_traversal(tmp_path):
    zip_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("../escape.jpg", b"not-an-image")

    with pytest.raises(HTTPException, match="不安全的文件路径"):
        DetectionService._safe_zip_images(zip_path, tmp_path / "extract")


def test_zip_rejects_more_than_batch_limit(tmp_path):
    zip_path = tmp_path / "too-many.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for index in range(21):
            archive.writestr(f"{index}.jpg", b"image")

    with pytest.raises(HTTPException, match="图片数量不能超过 20 张"):
        DetectionService._safe_zip_images(zip_path, tmp_path / "extract")


def test_zip_preserves_tiff_support(tmp_path):
    zip_path = tmp_path / "tiff.zip"
    output = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(output, format="TIFF")
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("sample.tiff", output.getvalue())

    extracted = DetectionService._safe_zip_images(zip_path, tmp_path / "extract")

    assert [path.suffix for path in extracted] == [".tiff"]


def test_supported_image_types_match_detection_page_options():
    assert {"image/jpeg", "image/png", "image/bmp", "image/tiff", "image/webp"} <= ALLOWED_IMAGE_TYPES
