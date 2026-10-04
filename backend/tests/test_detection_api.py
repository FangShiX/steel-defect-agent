"""检测 API 参数与响应契约测试。"""

import io
import base64
from datetime import datetime
from uuid import uuid4

from PIL import Image

from app.api.auth import get_current_user
from app.core.security import create_access_token, decode_access_token
from app.entity.db_models import AuthSession, User
from main import app


def _jpeg_bytes():
    output = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(output, format="JPEG")
    return output.getvalue()


def _issue_camera_token(db_session, user):
    token = create_access_token({"sub": str(user.id), "type": "access"})
    claims = decode_access_token(token)
    db_session.add(AuthSession(
        session_uuid=str(uuid4()), user_id=user.id,
        access_jti=claims["jti"], refresh_jti=str(uuid4()),
        access_expires_at=datetime.fromtimestamp(claims["exp"]),
        refresh_expires_at=datetime.now(),
    ))
    db_session.commit()
    return token


def test_single_detection_requires_authentication(client):
    response = client.post(
        "/api/detection/single",
        data={"model_id": "1"},
        files={"file": ("sample.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert response.status_code == 401


def test_single_detection_validates_threshold(client, db_session):
    user = User(username="api-user", email="api@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        response = client.post(
            "/api/detection/single",
            data={"model_id": "1", "conf_threshold": "1.5"},
            files={"file": ("sample.jpg", _jpeg_bytes(), "image/jpeg")},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 422


def test_video_detection_rejects_unsupported_format(client, db_session):
    user = User(username="video-user", email="video@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        response = client.post(
            "/api/detection/video",
            data={"model_id": "1"},
            files={"file": ("sample.txt", b"not-video", "text/plain")},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 400
    assert "不支持的视频格式" in response.json()["message"]


def test_camera_websocket_config_frame_and_close(client, db_session, monkeypatch):
    import sys
    from types import SimpleNamespace

    monkeypatch.setitem(
        sys.modules,
        "cv2",
        SimpleNamespace(IMREAD_COLOR=1, imdecode=lambda data, _mode: data),
    )
    user = User(username="camera-user", email="camera@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    token = _issue_camera_token(db_session, user)
    model_version = type(
        "ModelVersionStub",
        (),
        {
            "id": 1,
            "model_name": "ssdd_yolo11n_v1",
            "model_path": "models/steel_surface_defect_v1.0.0/ssdd_yolo11n_v1.pt",
        },
    )()
    model = object()
    monkeypatch.setattr("app.api.detection.SessionLocal", lambda: db_session)
    monkeypatch.setattr(
        "app.api.detection.detection_service.warmup_camera",
        lambda *_args: (model_version, model),
    )
    monkeypatch.setattr(
        "app.api.detection.detection_service.detect_camera_frame",
        lambda *_args: {
            "annotated_frame": base64.b64encode(_jpeg_bytes()).decode("ascii"),
            "detections": [],
            "object_count": 0,
            "inference_time": 12.5,
        },
    )

    with client.websocket_connect("/api/detection/camera") as websocket:
        websocket.send_json({"type": "auth", "token": token})
        websocket.send_json({
            "type": "config", "mode": "cpu", "conf": 0.25, "iou": 0.45,
            "model_id": 1,
        })
        config = websocket.receive_json()
        assert config["type"] == "config_ok"
        assert config["model_name"] == "ssdd_yolo11n_v1"
        assert config["request_id"]
        assert config["user_id"] == user.id
        websocket.send_json({
            "type": "frame",
            "data": base64.b64encode(_jpeg_bytes()).decode("ascii"),
        })
        result = websocket.receive_json()
        assert result["type"] == "result"
        assert result["frame_count"] == 1
        assert result["inference_time"] == 12.5
        assert result["request_id"] == config["request_id"]
        assert result["user_id"] == user.id
        websocket.send_json({"type": "close"})


def test_camera_websocket_rejects_invalid_config_without_disconnect(client, db_session, monkeypatch):
    user = User(username="camera-invalid", email="camera-invalid@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    token = _issue_camera_token(db_session, user)
    monkeypatch.setattr("app.api.detection.SessionLocal", lambda: db_session)

    with client.websocket_connect("/api/detection/camera") as websocket:
        websocket.send_json({"type": "auth", "token": token})
        websocket.send_json({"type": "config", "model_id": 1, "conf": "bad", "iou": 0.45})
        error = websocket.receive_json()
        assert error["type"] == "error"
        assert error["code"] == "INVALID_THRESHOLD"
        assert error["detail"]["code"] == "INVALID_THRESHOLD"
        assert error["retryable"] is False
        assert error["request_id"]
        websocket.send_json({"type": "close"})


def test_zip_detection_rejects_non_zip_extension(client, db_session):
    user = User(username="zip-user", email="zip@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        response = client.post(
            "/api/detection/zip",
            data={"model_id": "1"},
            files={"file": ("images.tar", b"invalid", "application/octet-stream")},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 400
    assert "仅支持 ZIP 压缩包" in response.json()["message"]


def test_zip_detection_rejects_invalid_archive(client, db_session, monkeypatch, tmp_path):
    from app.entity.db_models import DetectionScene, ModelVersion

    user = User(username="zip-invalid", email="zip-invalid@example.com", hashed_password="x")
    scene = DetectionScene(
        name="zip-scene", display_name="ZIP 场景", category="industry",
        class_names=["scratches"],
    )
    db_session.add_all([user, scene])
    db_session.flush()
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"weights")
    model = ModelVersion(
        scene_id=scene.id, version="v1", model_name="zip-model",
        model_type="yolo11n", model_path=str(weights), is_default=True, is_builtin=True,
    )
    db_session.add(model)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        response = client.post(
            "/api/detection/zip",
            data={"model_id": str(model.id)},
            files={"file": ("images.zip", b"invalid", "application/zip")},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 400
    assert "无效的 ZIP" in response.json()["message"]
