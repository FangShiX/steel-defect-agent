"""YOLO 图片、视频和摄像头检测 API。"""

import asyncio
import base64
import os
import tempfile
import threading
import time
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.concurrency import run_in_threadpool
from jwt import InvalidTokenError as JWTError
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.config.detection import (
    ALLOWED_VIDEO_SUFFIXES,
    DEFAULT_CONF_THRESHOLD,
    DEFAULT_IOU_THRESHOLD,
    DEFAULT_VIDEO_FRAME_SAMPLE_RATE,
    DEFAULT_VIDEO_MAX_FRAMES,
    MAX_VIDEO_FRAMES,
    MAX_VIDEO_SIZE,
    MAX_ZIP_SIZE,
    VIDEO_PROGRESS_TTL,
)
from app.core.logger import get_logger
from app.core.redis_client import redis_client
from app.core.security import decode_access_token
from app.database.session import SessionLocal, get_db
from app.entity.db_models import AuthSession
from app.entity.schemas import BatchDetectionResponse, DetectionResponse
from app.services.detection_service import detection_service
from app.services.history_service import history_service
from app.services.notification_service import notification_service
from app.services.operation_log_service import operation_log_service
from app.services.user_service import user_service
from app.services.authorization_service import authorization_service

router = APIRouter(prefix="/api/detection", tags=["detection"])
logger = get_logger(__name__)


@router.get("/models/status")
async def detection_model_status():
    return detection_service.warmup_status()

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff"}


@router.post("/single", response_model=DetectionResponse)
async def detect_single(
    file: UploadFile = File(...),
    model_id: int = Form(...),
    conf_threshold: float = Form(DEFAULT_CONF_THRESHOLD, ge=0, le=1),
    iou_threshold: float = Form(DEFAULT_IOU_THRESHOLD, ge=0, le=1),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=128),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await detection_service.detect_single(
        db, current_user.id, file, model_id, conf_threshold, iou_threshold, idempotency_key
    )


@router.post("/batch", response_model=BatchDetectionResponse)
async def detect_batch(
    files: list[UploadFile] = File(...),
    model_id: int = Form(...),
    conf_threshold: float = Form(DEFAULT_CONF_THRESHOLD, ge=0, le=1),
    iou_threshold: float = Form(DEFAULT_IOU_THRESHOLD, ge=0, le=1),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=128),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await detection_service.detect_batch(
        db, current_user.id, files, model_id, conf_threshold, iou_threshold,
        idempotency_key=idempotency_key,
    )


@router.post("/zip", response_model=BatchDetectionResponse, summary="ZIP 图片检测")
async def detect_zip(
    file: UploadFile = File(...),
    model_id: int = Form(...),
    conf_threshold: float = Form(DEFAULT_CONF_THRESHOLD, ge=0, le=1),
    iou_threshold: float = Form(DEFAULT_IOU_THRESHOLD, ge=0, le=1),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=128),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="仅支持 ZIP 压缩包")
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = tmp.name
            total_size = 0
            while chunk := await file.read(1024 * 1024):
                total_size += len(chunk)
                if total_size > MAX_ZIP_SIZE:
                    raise HTTPException(status_code=400, detail="ZIP 文件不能超过 50 MB")
                tmp.write(chunk)
        if total_size == 0:
            raise HTTPException(status_code=400, detail="上传 ZIP 为空")
        return await detection_service.detect_zip(
            db,
            current_user.id,
            tmp_path,
            model_id,
            conf_threshold,
            iou_threshold,
            file.filename,
            idempotency_key,
        )
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass


@router.post("/video", summary="视频检测")
async def detect_video(
    file: UploadFile = File(...),
    model_id: int = Form(...),
    conf_threshold: float = Form(DEFAULT_CONF_THRESHOLD, ge=0, le=1),
    iou_threshold: float = Form(DEFAULT_IOU_THRESHOLD, ge=0, le=1),
    frame_sample_rate: int = Form(DEFAULT_VIDEO_FRAME_SAMPLE_RATE, ge=1, le=60),
    max_frames: int = Form(DEFAULT_VIDEO_MAX_FRAMES, ge=1, le=MAX_VIDEO_FRAMES),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=128),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    suffix = os.path.splitext(file.filename or "")[1].lower()
    if suffix not in ALLOWED_VIDEO_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的视频格式: {suffix or '无扩展名'}",
        )
    model_version = detection_service._resolve_model(db, model_id, current_user.id)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name
            total_size = 0
            while chunk := await file.read(1024 * 1024):
                total_size += len(chunk)
                if total_size > MAX_VIDEO_SIZE:
                    raise HTTPException(status_code=400, detail="视频文件不能超过 50 MB")
                tmp.write(chunk)
        if total_size == 0:
            raise HTTPException(status_code=400, detail="上传视频为空")
    except Exception:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
        raise

    task = history_service.create_task(
        db,
        user_id=current_user.id,
        scene_id=model_version.scene_id,
        task_type="video",
        model_version_id=model_version.id,
        conf_threshold=conf_threshold,
        iou_threshold=iou_threshold,
        idempotency_key=idempotency_key,
    )
    history_service.mark_processing(db, task.id)
    task_id = task.id
    model_version_id = model_version.id
    redis_client.set_video_task(
        task_id,
        {"status": "processing", "progress": 0, "message": "视频处理中..."},
        ttl=VIDEO_PROGRESS_TTL,
    )

    def update_progress(current_frame, total_frames):
        redis_client.set_video_task(
            task_id,
            {
                "status": "processing",
                "progress": round(current_frame / total_frames * 100, 2),
                "current_frame": current_frame,
                "total_frames": total_frames,
                "message": "视频处理中...",
            },
            ttl=VIDEO_PROGRESS_TTL,
        )

    def run_video_detection():
        try:
            result = detection_service.detect_video(
                video_path=tmp_path,
                model_id=model_version_id,
                task_id=task_id,
                conf=conf_threshold,
                iou=iou_threshold,
                frame_sample_rate=frame_sample_rate,
                max_frames=max_frames,
                progress_callback=update_progress,
            )
            redis_client.set_video_task(
                task_id,
                {
                    "status": "completed",
                    "progress": 100,
                    "message": f"检测完成，共处理 {result['processed_frames']} 个关键帧",
                    "result": result,
                },
                ttl=VIDEO_PROGRESS_TTL,
            )
        except Exception as exc:
            redis_client.set_video_task(
                task_id,
                {"status": "failed", "progress": 0, "message": "视频检测失败，请稍后重试"},
                ttl=VIDEO_PROGRESS_TTL,
            )
        finally:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass

    threading.Thread(target=run_video_detection, daemon=True).start()
    logger.info(
        "视频任务已创建 task_id=%s user_id=%s filename=%s size=%s",
        task_id, current_user.id, file.filename, total_size,
    )
    return {
        "task_id": task_id,
        "public_task_id": task.public_task_id,
        "status": "processing",
        "message": "视频已上传，正在后台处理中",
        "filename": file.filename,
    }


@router.get("/video/status/{task_id}", summary="查询视频检测进度")
async def get_video_status(
    task_id: int,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    can_read_all = authorization_service.has_permission(db, current_user, "detection:task:read_all")
    task = history_service.get_task_detail(db, task_id, current_user.id, can_read_all)
    if task.task_type != "video":
        raise HTTPException(status_code=400, detail="该任务不是视频检测任务")
    progress = redis_client.get_video_task(task_id)
    if progress:
        return {"task_id": task_id, "public_task_id": task.public_task_id, **progress}
    return {
        "task_id": task.id,
        "public_task_id": task.public_task_id,
        "status": task.status,
        "progress": 100 if task.status == "completed" else 0,
        "message": task.error_message or task.status,
        "task_type": task.task_type,
        "total_images": task.total_images,
        "total_objects": task.total_objects,
        "total_inference_time": task.total_inference_time,
    }


def _get_websocket_user(token: str | None, db: Session):
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        if payload.get("type") not in (None, "access"):
            return None
        user_id = int(payload.get("sub"))
    except (JWTError, TypeError, ValueError):
        return None
    try:
        user = user_service.get_user_by_id(db, user_id)
        if not user.is_active:
            return None
        jti = payload.get("jti")
        if jti and not db.query(AuthSession).filter(AuthSession.access_jti == jti, AuthSession.revoked_at.is_(None)).first():
            return None
        return user
    except HTTPException:
        return None


@router.websocket("/camera")
async def camera_detection(websocket: WebSocket):
    db = SessionLocal()
    await websocket.accept()
    request_id = websocket.headers.get("x-request-id") or uuid4().hex
    try:
        auth_message = await asyncio.wait_for(websocket.receive_json(), timeout=10)
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError):
        await websocket.close(code=1008, reason="认证消息无效")
        db.close()
        return
    token = auth_message.get("token") if auth_message.get("type") == "auth" else None
    user = _get_websocket_user(token, db)
    if not user:
        await websocket.close(code=1008, reason="无效的认证凭据")
        db.close()
        return
    connection_id = id(websocket)

    async def send_ws_error(code: str, detail: str, *, retryable: bool = False, status_code: int = 400):
        operation_log_service.record(
            db,
            user=user,
            module="detection",
            action="websocket_error",
            target_type="camera_session",
            target_id=str(connection_id),
            description=f"WebSocket error {code}",
            status="failure",
            error_message=detail,
            request_id=request_id,
        )
        await websocket.send_json({
            "type": "error",
            "code": code,
            "error_code": code,
            "status_code": status_code,
            "message": detail,
            "detail": {"code": code, "message": detail},
            "request_id": request_id,
            "task_id": None,
            "session_id": None,
            "user_id": user.id,
            "retryable": retryable,
        })

    mode = "cpu"
    conf = DEFAULT_CONF_THRESHOLD
    iou = DEFAULT_IOU_THRESHOLD
    model_version = None
    model = None
    model_id = None
    frame_count = 0
    fps_window_started = time.perf_counter()
    fps_window_count = 0
    current_fps = 0.0
    last_frame_time = 0.0
    logger.info("摄像头连接建立 connection_id=%s user_id=%s", connection_id, user.id)
    try:
        while True:
            message = await websocket.receive_json()
            message_type = message.get("type")
            if message_type == "config":
                mode = message.get("mode", "cpu")
                if mode not in {"cpu", "gpu"}:
                    await send_ws_error("INVALID_MODE", "mode must be cpu or gpu")
                    continue
                try:
                    conf = float(message.get("conf", DEFAULT_CONF_THRESHOLD))
                    iou = float(message.get("iou", DEFAULT_IOU_THRESHOLD))
                except (TypeError, ValueError):
                    await send_ws_error("INVALID_THRESHOLD", "conf and iou must be numeric")
                    continue
                if not 0 <= conf <= 1 or not 0 <= iou <= 1:
                    await send_ws_error("INVALID_THRESHOLD", "conf and iou must be between 0 and 1")
                    continue
                try:
                    model_id = int(message.get("model_id"))
                    model_version, model = await run_in_threadpool(
                        detection_service.warmup_camera, db, model_id, mode, conf, iou, user.id
                    )
                except Exception as exc:
                    logger.exception("摄像头模型初始化失败 connection_id=%s", connection_id)
                    notification_service.safe_create(
                        db, user.id, "model_anomaly", "Model anomaly",
                        "Camera model loading failed; please check the model configuration.",
                        resource_type="model", resource_id=model_id, request_id=request_id,
                    )
                    await send_ws_error("MODEL_LOAD_FAILED", "model loading failed", retryable=True, status_code=503)
                    continue
                await websocket.send_json(
                    {
                        "type": "config_ok",
                        "mode": mode,
                        "model_id": model_version.id,
                        "model_name": model_version.model_name,
                        "request_id": request_id,
                        "task_id": None,
                        "session_id": None,
                        "user_id": user.id,
                        "message": f"配置成功，模式: {mode}，模型: {model_version.model_name}",
                    }
                )
            elif message_type == "frame":
                if model is None:
                    await send_ws_error("CONFIG_REQUIRED", "send config before sending frames")
                    continue
                now = time.perf_counter()
                if mode == "cpu" and now - last_frame_time < 0.3:
                    await websocket.send_json({
                        "type": "frame_skipped", "retry_after_ms": 300,
                        "request_id": request_id, "task_id": None,
                        "session_id": None, "user_id": user.id,
                    })
                    continue
                last_frame_time = now
                try:
                    import cv2
                    import numpy as np

                    frame_bytes = base64.b64decode(message.get("data", ""), validate=True)
                    frame = cv2.imdecode(np.frombuffer(frame_bytes, np.uint8), cv2.IMREAD_COLOR)
                    if frame is None:
                        raise ValueError("无法解码摄像头帧")
                    result = await run_in_threadpool(
                        detection_service.detect_camera_frame,
                        model_version, model, frame, mode, conf, iou,
                    )
                    frame_count += 1
                    fps_window_count += 1
                    elapsed = now - fps_window_started
                    if elapsed >= 1:
                        current_fps = fps_window_count / elapsed
                        fps_window_count = 0
                        fps_window_started = now
                    await websocket.send_json(
                        {
                            "type": "result",
                            **result,
                            "fps": round(current_fps, 1),
                            "frame_count": frame_count,
                            "request_id": request_id,
                            "task_id": None,
                            "session_id": None,
                            "user_id": user.id,
                        }
                    )
                except Exception as exc:
                    logger.warning("摄像头帧处理失败 connection_id=%s error=%s", connection_id, exc)
                    await send_ws_error("FRAME_PROCESSING_FAILED", "frame processing failed", retryable=True, status_code=422)
            elif message_type == "close":
                await websocket.close(code=1000, reason="Client requested close")
                break
            else:
                await send_ws_error("UNKNOWN_MESSAGE_TYPE", "unknown message type")
    except WebSocketDisconnect as exc:
        logger.info(
            "摄像头 WebSocket 断开 connection_id=%s code=%s reason=%s",
            connection_id,
            exc.code,
            exc.reason,
        )
    finally:
        db.close()
        logger.info("摄像头连接关闭 connection_id=%s frames=%s", connection_id, frame_count)
