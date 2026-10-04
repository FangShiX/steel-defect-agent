"""YOLO 图片、视频和摄像头推理服务。"""

import base64
import io
import os
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session, joinedload

from app.config.detection import (
    ALLOWED_IMAGE_TYPES,
    DEFAULT_IMAGE_SIZE,
    MAX_BATCH_SIZE,
    MAX_IMAGE_SIZE,
    DEFAULT_VIDEO_MAX_FRAMES,
    MAX_ZIP_EXTRACTED_SIZE,
)
from app.core.logger import get_logger
from app.core.artifact_access import register_artifact
from app.entity.db_models import ModelVersion, User
from app.database.session import SessionLocal
from app.services.history_service import history_service
from app.services.notification_service import notification_service
from app.storage.minio_client import MinIOClient


logger = get_logger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
VIDEO_TRACK_IOU_THRESHOLD = 0.5
VIDEO_TRACK_MAX_MISSED_FRAMES = 2
VIDEO_TRACK_SCENE_CHANGE_THRESHOLD = 40
AGENT_ARTIFACT_TTL_SECONDS = 24 * 60 * 60


def _cleanup_agent_artifacts(artifact_dir: Path) -> None:
    cutoff = time.time() - AGENT_ARTIFACT_TTL_SECONDS
    for artifact_path in artifact_dir.glob("annotated_*.jpg"):
        try:
            if artifact_path.stat().st_mtime < cutoff:
                artifact_path.unlink()
        except OSError:
            logger.debug("Unable to remove stale agent artifact: %s", artifact_path)
class DetectionService:
    """编排模型加载、推理、对象存储和历史落库。"""

    def __init__(self):
        self._models = {}
        self._inference_locks = {}
        self._model_lock = threading.Lock()
        self._warmup_status = "idle"
        self._warmup_error = ""

    def warmup_models(self):
        from app.database.session import SessionLocal

        db = SessionLocal()
        self._warmup_status = "loading"
        try:
            versions = db.query(ModelVersion).filter(ModelVersion.status == "active").all()
            for version in versions:
                self._get_model(version)
            self._warmup_status = "ready"
        except Exception as exc:
            self._warmup_status = "error"
            self._warmup_error = "Detection model warmup failed"
            logger.warning("检测模型预热失败 error_type=%s", type(exc).__name__)
            for admin in db.query(User).filter(User.is_superuser.is_(True), User.is_active.is_(True)).all():
                notification_service.safe_create(
                    db, admin.id, "model_anomaly", "Detection model unavailable",
                    "One or more detection models failed to warm up; check the server and retry.",
                    resource_type="detection_model",
                )
        finally:
            db.close()

    def warmup_status(self):
        return {"status": self._warmup_status, "error": self._warmup_error, "loaded": len(self._models)}

    @staticmethod
    def _resolve_model(db: Session, model_id: int, user_id: int | None = None) -> ModelVersion:
        model_version = (
            db.query(ModelVersion)
            .filter(ModelVersion.id == model_id, ModelVersion.status == "active")
            .first()
        )
        if model_version and user_id is not None and not model_version.is_builtin and model_version.owner_id != user_id:
            model_version = None
        if not model_version:
            raise HTTPException(status_code=404, detail="模型版本不存在或不可用")
        return model_version

    @staticmethod
    def _resolve_model_path(model_path: str) -> Path:
        path = Path(model_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        path = path.resolve()
        if not path.is_file():
            raise HTTPException(status_code=500, detail="模型权重不存在")
        return path

    def _get_model(self, model_version: ModelVersion):
        model_path = self._resolve_model_path(model_version.model_path)
        cache_key = (model_version.id, str(model_path))
        cached = self._models.get(cache_key)
        if cached is not None:
            return cached

        with self._model_lock:
            cached = self._models.get(cache_key)
            if cached is None:
                try:
                    from ultralytics import YOLO

                    cached = YOLO(str(model_path))
                except ImportError as exc:
                    if getattr(exc, "name", None) == "ultralytics":
                        raise HTTPException(status_code=500, detail="未安装 Ultralytics 推理依赖") from exc
                    logger.error("Ultralytics 推理依赖加载失败 error_type=%s", type(exc).__name__)
                    raise HTTPException(status_code=500, detail="Ultralytics 推理依赖加载失败") from exc
                except Exception as exc:
                    logger.error("模型加载失败 model_id=%s error_type=%s", model_version.id, type(exc).__name__)
                    raise HTTPException(status_code=500, detail="模型权重加载失败") from exc
                self._models[cache_key] = cached
                self._inference_locks[cache_key] = threading.Lock()
        return cached

    def _predict(self, model_version, model, image, task):
        model_path = self._resolve_model_path(model_version.model_path)
        cache_key = (model_version.id, str(model_path))
        inference_lock = self._inference_locks.setdefault(cache_key, threading.Lock())
        with inference_lock:
            return model.predict(
                source=image,
                conf=task.conf_threshold,
                iou=task.iou_threshold,
                imgsz=task.image_size,
                verbose=False,
            )

    def _predict_frame(self, model_version, model, frame, conf, iou, image_size, device):
        model_path = self._resolve_model_path(model_version.model_path)
        cache_key = (model_version.id, str(model_path))
        inference_lock = self._inference_locks.setdefault(cache_key, threading.Lock())
        with inference_lock:
            return model.predict(
                source=frame,
                conf=conf,
                iou=iou,
                imgsz=image_size,
                device=device,
                half=False,
                save=False,
                verbose=False,
            )

    @staticmethod
    async def _read_image(file: UploadFile) -> tuple[bytes, Image.Image]:
        if file.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(status_code=400, detail=f"不支持的图片类型: {file.content_type}")
        data = await file.read(MAX_IMAGE_SIZE + 1)
        if not data:
            raise HTTPException(status_code=400, detail="上传图片为空")
        if len(data) > MAX_IMAGE_SIZE:
            raise HTTPException(status_code=400, detail="图片大小不能超过 10 MB")
        try:
            image = Image.open(io.BytesIO(data))
            image.verify()
            image = Image.open(io.BytesIO(data)).convert("RGB")
        except (UnidentifiedImageError, OSError) as exc:
            raise HTTPException(status_code=400, detail="图片内容无法解析") from exc
        return data, image

    @staticmethod
    def _parse_result(result, scene) -> list[dict]:
        names = result.names
        class_names_cn = scene.class_names_cn or {}
        parsed = []
        if result.boxes is None:
            return parsed
        for box in result.boxes:
            class_id = int(box.cls.item())
            class_name = names[class_id] if isinstance(names, dict) else names[class_id]
            parsed.append(
                {
                    "class_id": class_id,
                    "class_name": class_name,
                    "class_name_cn": class_names_cn.get(class_name, class_name),
                    "confidence": round(float(box.conf.item()), 6),
                    "bbox": [round(float(value), 2) for value in box.xyxy[0].tolist()],
                }
            )
        return parsed

    @staticmethod
    def _encode_annotated_image(result) -> bytes:
        annotated_bgr = result.plot()
        annotated_rgb = annotated_bgr[:, :, ::-1]
        output = io.BytesIO()
        Image.fromarray(annotated_rgb).save(output, format="JPEG", quality=90)
        return output.getvalue()

    async def _detect_file(self, file, task, model_version, model, minio_client):
        filename = Path(file.filename or "image.jpg").name
        source_bytes, image = await self._read_image(file)
        started_at = time.perf_counter()
        try:
            results = await run_in_threadpool(self._predict, model_version, model, image, task)
        except Exception as exc:
            logger.exception("YOLO 推理失败 task_id=%s file=%s", task.id, filename)
            raise HTTPException(status_code=500, detail="YOLO 模型推理失败") from exc
        inference_time = round((time.perf_counter() - started_at) * 1000, 2)
        if not results:
            raise HTTPException(status_code=500, detail="YOLO 模型未返回推理结果")

        result = results[0]
        detections = self._parse_result(result, task.scene)
        object_id = uuid4().hex
        suffix = Path(filename).suffix.lower() or ".jpg"
        base_path = f"detections/{task.user_id}/{task.id}"
        original_object_key = f"{base_path}/original/{object_id}{suffix}"
        image_url = minio_client.upload_bytes(
            original_object_key,
            source_bytes,
            file.content_type,
        )
        try:
            annotated_object_key = f"{base_path}/annotated/{object_id}.jpg"
            annotated_url = minio_client.upload_bytes(
                annotated_object_key,
                self._encode_annotated_image(result),
                "image/jpeg",
            )
        except Exception:
            minio_client.delete_by_url(image_url)
            raise

        db_results = [
            {
                "image_path": image_url,
                "annotated_image_url": annotated_url,
                "original_object_key": original_object_key,
                "annotated_object_key": annotated_object_key,
                **item,
                "inference_time": inference_time,
                "image_width": image.width,
                "image_height": image.height,
            }
            for item in detections
        ]
        return {
            "filename": filename,
            "image_url": image_url,
            "annotated_image_url": annotated_url,
            "image_width": image.width,
            "image_height": image.height,
            "total_objects": len(detections),
            "inference_time_ms": inference_time,
            "objects": detections,
            "db_results": db_results,
        }

    async def detect_single(
        self, db, user_id, file, model_id, conf_threshold, iou_threshold,
        idempotency_key=None,
    ):
        model_version = self._resolve_model(db, model_id, user_id)
        task = history_service.create_task(
            db,
            user_id=user_id,
            scene_id=model_version.scene_id,
            task_type="single",
            model_version_id=model_version.id,
            conf_threshold=conf_threshold,
            iou_threshold=iou_threshold,
            image_size=DEFAULT_IMAGE_SIZE,
            idempotency_key=idempotency_key,
        )
        history_service.mark_processing(db, task.id)
        try:
            result = await self._detect_file(
                file, task, model_version, self._get_model(model_version), MinIOClient()
            )
            if result["db_results"]:
                history_service.add_results(db, task.id, result["db_results"])
            history_service.mark_completed(
                db, task.id, total_images=1, total_objects=result["total_objects"],
                total_inference_time=result["inference_time_ms"],
            )
        except Exception as exc:
            raw_detail = exc.detail if isinstance(exc, HTTPException) else None
            detail = (
                raw_detail
                if isinstance(raw_detail, str) and "/" not in raw_detail and "\\" not in raw_detail and "://" not in raw_detail
                else "Detection failed"
            )
            history_service.mark_failed(db, task.id, detail)
            raise
        result.pop("db_results")
        return {"task_id": task.id, "public_task_id": task.public_task_id, "status": "completed", **result}

    async def detect_batch(
        self,
        db,
        user_id,
        files,
        model_id,
        conf_threshold,
        iou_threshold,
        task_type="batch",
        idempotency_key=None,
    ):
        if not files or len(files) > MAX_BATCH_SIZE:
            raise HTTPException(status_code=400, detail=f"批量检测需上传 1-{MAX_BATCH_SIZE} 张图片")
        model_version = self._resolve_model(db, model_id, user_id)
        task = history_service.create_task(
            db,
            user_id=user_id,
            scene_id=model_version.scene_id,
            task_type=task_type,
            model_version_id=model_version.id,
            conf_threshold=conf_threshold,
            iou_threshold=iou_threshold,
            image_size=DEFAULT_IMAGE_SIZE,
            idempotency_key=idempotency_key,
        )
        history_service.mark_processing(db, task.id)
        try:
            model = self._get_model(model_version)
            minio_client = MinIOClient()
        except Exception as exc:
            history_service.mark_failed(db, task.id, "Detection service initialization failed")
            raise

        items = []
        db_results = []
        total_objects = 0
        total_inference_time = 0.0
        for file in files:
            try:
                result = await self._detect_file(file, task, model_version, model, minio_client)
                db_results.extend(result.pop("db_results"))
                total_objects += result["total_objects"]
                total_inference_time += result["inference_time_ms"]
                items.append({"file_name": result.pop("filename"), "status": "completed", **result})
            except Exception as exc:
                detail = exc.detail if isinstance(exc, HTTPException) else "检测处理失败"
                items.append({"file_name": Path(file.filename or "unknown").name, "status": "failed", "error": str(detail)})

        try:
            if db_results:
                history_service.add_results(db, task.id, db_results)
            history_service.mark_completed(
                db, task.id, total_images=len(files), total_objects=total_objects,
                total_inference_time=round(total_inference_time, 2),
            )
        except Exception:
            history_service.mark_failed(db, task.id, "检测结果保存失败")
            raise
        success_count = sum(item["status"] == "completed" for item in items)
        return {
            "task_id": task.id,
            "public_task_id": task.public_task_id,
            "status": "completed",
            "source": task_type,
            "success_count": success_count,
            "failed_count": len(items) - success_count,
            "items": items,
        }

    @staticmethod
    def _safe_zip_images(zip_path: str, extract_dir: str) -> list[Path]:
        """校验 ZIP 内容并安全解压图片，阻止路径穿越和压缩炸弹。"""
        # Keep this aligned with the existing single-image upload contract.
        allowed_suffixes = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".tif"}
        extract_root = Path(extract_dir).resolve()
        image_paths = []
        total_size = 0
        try:
            archive = zipfile.ZipFile(zip_path)
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=400, detail="无效的 ZIP 压缩包") from exc

        with archive:
            image_members = []
            for member in archive.infolist():
                if member.is_dir() or member.filename.startswith("__MACOSX/"):
                    continue
                member_path = Path(member.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise HTTPException(status_code=400, detail="ZIP 包含不安全的文件路径")
                if member.file_size > MAX_IMAGE_SIZE:
                    raise HTTPException(status_code=400, detail=f"ZIP 内图片超过 10 MB: {member.filename}")
                total_size += member.file_size
                if total_size > MAX_ZIP_EXTRACTED_SIZE:
                    raise HTTPException(status_code=400, detail="ZIP 解压后总大小不能超过 200 MB")
                if member_path.suffix.lower() in allowed_suffixes:
                    image_members.append(member)

            if not image_members:
                raise HTTPException(status_code=400, detail="ZIP 中没有支持的图片")
            if len(image_members) > MAX_BATCH_SIZE:
                raise HTTPException(
                    status_code=400,
                    detail=f"ZIP 中图片数量不能超过 {MAX_BATCH_SIZE} 张",
                )

            for member in image_members:
                target = (extract_root / member.filename).resolve()
                if extract_root not in target.parents:
                    raise HTTPException(status_code=400, detail="ZIP 包含不安全的文件路径")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                image_paths.append(target)
        return image_paths

    async def detect_zip(
        self,
        db,
        user_id,
        zip_path,
        model_id,
        conf_threshold,
        iou_threshold,
        original_filename,
        idempotency_key=None,
    ):
        """安全解压 ZIP，并复用批量检测流程。"""
        with tempfile.TemporaryDirectory(prefix="ssdd_zip_") as extract_dir:
            image_paths = self._safe_zip_images(zip_path, extract_dir)
            uploads = []
            handles = []
            try:
                for image_path in image_paths:
                    handle = image_path.open("rb")
                    handles.append(handle)
                    content_type = {
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".png": "image/png",
                        ".bmp": "image/bmp",
                        ".webp": "image/webp",
                        ".tiff": "image/tiff",
                        ".tif": "image/tiff",
                    }[image_path.suffix.lower()]
                    uploads.append(
                        UploadFile(
                            filename=image_path.name,
                            file=handle,
                            headers={"content-type": content_type},
                        )
                    )
                result = await self.detect_batch(
                    db,
                    user_id,
                    uploads,
                    model_id,
                    conf_threshold,
                    iou_threshold,
                    task_type="zip",
                    idempotency_key=idempotency_key,
                )
                result["zip_filename"] = original_filename
                result["total_images_in_zip"] = len(image_paths)
                return result
            finally:
                for handle in handles:
                    handle.close()

    @staticmethod
    def _draw_detections(frame, detections):
        import cv2

        annotated = frame.copy()
        for detection in detections:
            x1, y1, x2, y2 = (int(value) for value in detection["bbox"])
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 165, 255), 2)
            label = f"{detection['class_name']} {detection['confidence']:.2f}"
            cv2.putText(
                annotated, label, (x1, max(18, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX,
                0.5, (0, 165, 255), 2,
            )
        return annotated

    @staticmethod
    def _bbox_iou(left, right):
        intersection_width = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
        intersection_height = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
        intersection = intersection_width * intersection_height
        left_area = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
        right_area = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
        union = left_area + right_area - intersection
        return intersection / union if union > 0 else 0.0

    @classmethod
    def _update_video_tracks(
        cls,
        tracks,
        active_tracks,
        detections,
        frame_index,
        inference_time,
        width,
        height,
        reset=False,
    ):
        if reset:
            active_tracks.clear()

        candidates = []
        for track_index, track in enumerate(active_tracks):
            for detection_index, detection in enumerate(detections):
                if track["class_id"] != detection["class_id"]:
                    continue
                overlap = cls._bbox_iou(track["bbox"], detection["bbox"])
                if overlap >= VIDEO_TRACK_IOU_THRESHOLD:
                    candidates.append((overlap, track_index, detection_index))

        matched_tracks = set()
        matched_detections = set()
        for _overlap, track_index, detection_index in sorted(candidates, reverse=True):
            if track_index in matched_tracks or detection_index in matched_detections:
                continue
            track = active_tracks[track_index]
            detection = detections[detection_index]
            track["bbox"] = detection["bbox"]
            track["missed_frames"] = 0
            if detection["confidence"] > track["result"]["confidence"]:
                track["result"] = {
                    "image_path": f"frame_{frame_index}.jpg",
                    **detection,
                    "inference_time": inference_time,
                    "image_width": width,
                    "image_height": height,
                }
            matched_tracks.add(track_index)
            matched_detections.add(detection_index)

        for track_index, track in enumerate(active_tracks):
            if track_index not in matched_tracks:
                track["missed_frames"] += 1
        active_tracks[:] = [
            track
            for track in active_tracks
            if track["missed_frames"] <= VIDEO_TRACK_MAX_MISSED_FRAMES
        ]

        for detection_index, detection in enumerate(detections):
            if detection_index in matched_detections:
                continue
            track = {
                "class_id": detection["class_id"],
                "bbox": detection["bbox"],
                "missed_frames": 0,
                "result": {
                    "image_path": f"frame_{frame_index}.jpg",
                    **detection,
                    "inference_time": inference_time,
                    "image_width": width,
                    "image_height": height,
                },
            }
            tracks.append(track)
            active_tracks.append(track)

    def detect_video(
        self,
        video_path,
        model_id,
        task_id,
        conf=0.25,
        iou=0.45,
        frame_sample_rate=5,
        max_frames=DEFAULT_VIDEO_MAX_FRAMES,
        progress_callback=None,
    ):
        """按采样间隔处理视频，生成关键帧、标注视频和检测记录。"""
        import cv2

        db = SessionLocal()
        cap = None
        writer = None
        output_path = None
        h264_path = None
        try:
            model_version = self._resolve_model(db, model_id)
            model = self._get_model(model_version)
            task = history_service._get_task_or_404(db, task_id)
            cap = cv2.VideoCapture(str(video_path))
            if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
                cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
            if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
                cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000)
            if not cap.isOpened():
                raise RuntimeError("无法打开视频文件")

            total_frames = max(0, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if width <= 0 or height <= 0:
                raise RuntimeError("无法读取视频分辨率")
            duration_seconds = total_frames / fps if fps > 0 else 0
            effective_interval = max(frame_sample_rate, max(1, total_frames // max_frames))
            estimated_samples = min(max_frames, (total_frames + effective_interval - 1) // effective_interval)
            task.total_images = estimated_samples
            db.commit()

            output_file = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            output_path = output_file.name
            output_file.close()
            writer = cv2.VideoWriter(
                output_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
            )
            if not writer.isOpened():
                raise RuntimeError("无法创建标注视频")

            key_frames = []
            tracks = []
            active_tracks = []
            total_inference_time = 0.0
            processed_frames = 0
            frame_index = 0
            previous_gray = None
            last_detections = []

            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (100, 100))
                has_previous_frame = previous_gray is not None
                frame_difference = cv2.absdiff(previous_gray, gray).mean() if has_previous_frame else 0
                scene_changed = not has_previous_frame or frame_difference > 10
                previous_gray = gray
                should_sample = frame_index % effective_interval == 0 or scene_changed

                if should_sample and processed_frames < max_frames:
                    started_at = time.perf_counter()
                    results = self._predict_frame(
                        model_version, model, frame, conf, iou, DEFAULT_IMAGE_SIZE, "cpu"
                    )
                    inference_time = round((time.perf_counter() - started_at) * 1000, 2)
                    result = results[0]
                    detections = self._parse_result(result, task.scene)
                    last_detections = detections
                    processed_frames += 1
                    total_inference_time += inference_time
                    self._update_video_tracks(
                        tracks, active_tracks, detections, frame_index, inference_time,
                        width, height,
                        reset=frame_difference > VIDEO_TRACK_SCENE_CHANGE_THRESHOLD,
                    )
                    annotated = self._draw_detections(frame, detections)
                    encoded_frame = None
                    if len(key_frames) < 6:
                        encoded_ok, buffer = cv2.imencode(
                            ".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 70]
                        )
                        if encoded_ok:
                            encoded_frame = base64.b64encode(buffer).decode("ascii")
                    key_frames.append(
                        {
                            "frame_index": frame_index,
                            "timestamp": round(frame_index / fps, 2),
                            "annotated_image_base64": encoded_frame,
                            "object_count": len(detections),
                            "detections": detections,
                            "inference_time": inference_time,
                        }
                    )
                else:
                    annotated = self._draw_detections(frame, last_detections)
                writer.write(annotated)
                frame_index += 1
                if progress_callback and total_frames:
                    progress_callback(frame_index, total_frames)

            cap.release()
            cap = None
            writer.release()
            writer = None
            if frame_index == 0:
                raise RuntimeError("视频中没有可读取的帧")

            db_results = [track["result"] for track in tracks]
            class_counts = {}
            for result in db_results:
                class_counts[result["class_name"]] = class_counts.get(result["class_name"], 0) + 1
            total_objects = len(db_results)

            h264_path = output_path.replace(".mp4", "_h264.mp4")
            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg:
                try:
                    subprocess.run(
                        [ffmpeg, "-y", "-i", output_path, "-c:v", "libx264", "-preset", "fast",
                         "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", h264_path],
                        capture_output=True, timeout=300, check=True,
                    )
                    os.replace(h264_path, output_path)
                    h264_path = None
                except (OSError, subprocess.SubprocessError):
                    logger.warning("ffmpeg 转码失败，保留 mp4v 视频", exc_info=True)

            annotated_video_url = None
            try:
                annotated_video_url = MinIOClient().upload_file(
                    f"detections/{task_id}/annotated_video.mp4", output_path
                )
            except Exception:
                logger.warning("标注视频上传失败，仅返回关键帧和统计", exc_info=True)

            if db_results:
                history_service.add_results(db, task_id, db_results)
            history_service.mark_completed(
                db, task_id, total_images=processed_frames, total_objects=total_objects,
                total_inference_time=round(total_inference_time, 2),
            )
            logger.info(
                "视频检测完成 task_id=%s frames=%s sampled=%s objects=%s",
                task_id, frame_index, processed_frames, total_objects,
            )
            return {
                "task_id": task_id,
                "model": {
                    "id": model_version.id,
                    "name": model_version.model_name,
                    "version": model_version.version,
                    "path": model_version.model_path,
                },
                "total_frames": total_frames or frame_index,
                "processed_frames": processed_frames,
                "frame_sample_rate": effective_interval,
                "fps": round(fps, 2),
                "duration_seconds": round(duration_seconds, 2),
                "video_resolution": {"width": width, "height": height},
                "total_objects": total_objects,
                "class_counts": class_counts,
                "key_frames": key_frames,
                "annotated_video_url": annotated_video_url,
                "total_inference_time": round(total_inference_time, 2),
            }
        except Exception as exc:
            logger.exception("视频检测失败 task_id=%s", task_id)
            history_service.mark_failed(db, task_id, "Video detection failed")
            raise
        finally:
            if cap is not None:
                cap.release()
            if writer is not None:
                writer.release()
            for path in (output_path, h264_path):
                if path:
                    try:
                        os.unlink(path)
                    except FileNotFoundError:
                        pass
            # The video worker owns this session in production, but tests and
            # callers may inject a shared session. Leave lifecycle ownership
            # to the caller so returned ORM identities remain usable.

    def warmup_camera(self, db, model_id, mode, conf, iou, user_id=None):
        import numpy as np

        model_version = self._resolve_model(db, model_id, user_id)
        model = self._get_model(model_version)
        device = "cpu" if mode == "cpu" else "0"
        image_size = 416 if mode == "cpu" else 640
        self._predict_frame(
            model_version, model, np.zeros((480, 640, 3), dtype=np.uint8),
            conf, iou, image_size, device,
        )
        return model_version, model

    def detect_camera_frame(self, model_version, model, frame, mode, conf, iou):
        import cv2

        image_size = 416 if mode == "cpu" else 640
        device = "cpu" if mode == "cpu" else "0"
        started_at = time.perf_counter()
        results = self._predict_frame(
            model_version, model, frame, conf, iou, image_size, device
        )
        inference_time = round((time.perf_counter() - started_at) * 1000, 2)
        result = results[0]
        detections = self._parse_result(result, model_version.scene)
        encoded_ok, buffer = cv2.imencode(
            ".jpg", result.plot(), [cv2.IMWRITE_JPEG_QUALITY, 70]
        )
        if not encoded_ok:
            raise RuntimeError("标注帧编码失败")
        return {
            "annotated_frame": base64.b64encode(buffer).decode("ascii"),
            "detections": detections,
            "object_count": len(detections),
            "inference_time": inference_time,
            "model_id": model_version.id,
            "model_name": model_version.model_name,
        }


    def _get_default_model(self):
        """获取默认模型实例（供 Agent Tool 使用）"""
        from app.database.session import SessionLocal

        db = SessionLocal()
        try:
            model_version = (
                db.query(ModelVersion)
                .options(joinedload(ModelVersion.scene))
                .filter(ModelVersion.status == "active", ModelVersion.is_default == True)
                .first()
            )
            if not model_version:
                model_version = (
                    db.query(ModelVersion)
                    .options(joinedload(ModelVersion.scene))
                    .filter(ModelVersion.status == "active")
                    .first()
                )
            if not model_version:
                raise RuntimeError("数据库中没有可用的模型版本，请先注册模型")
            # Access scene within the session to avoid detached lazy-load
            class_names_cn = (model_version.scene.class_names_cn or {}) if model_version.scene else {}
            return self._get_model(model_version), model_version, class_names_cn
        finally:
            db.close()

    def _detect_file_sync(
        self, image_path: str, *, conf: float = 0.25, iou: float = 0.45,
        user_id: int | None = None, task_type: str = "single",
    ) -> dict:
        """同步检测本地图片文件（供 Agent Tool 调用）。user_id 不为 None 时写入 DetectionTask。"""
        model, model_version, class_names_cn = self._get_default_model()

        # ── 创建 DetectionTask（Agent 调用时） ──
        task_id = None
        _db = None
        if user_id is not None:
            from app.database.session import SessionLocal as _SessionLocal
            _db = _SessionLocal()
            try:
                task = history_service.create_task(
                    _db, user_id=user_id, scene_id=model_version.scene_id,
                    task_type=task_type, model_version_id=model_version.id,
                    conf_threshold=conf, iou_threshold=iou,
                    image_size=640,
                )
                history_service.mark_processing(_db, task.id)
                task_id = task.id
                logger.info("Agent检测已创建 DetectionTask id=%s user_id=%s scene_id=%s", task_id, user_id, model_version.scene_id)
            except Exception as exc:
                logger.exception("Agent检测创建 DetectionTask 失败: %s", exc)
                if _db:
                    _db.close()
                _db = None

        try:
            results = model.predict(
                source=image_path, conf=conf, iou=iou, imgsz=640, device="cpu",
                save=False, verbose=False,
            )
            result = results[0]

            detections = []
            class_counts = {}
            total_objects = 0

            if result.boxes is not None and len(result.boxes) > 0:
                for box in result.boxes:
                    cls_id = int(box.cls.item())
                    cls_name = model.names.get(cls_id, f"class_{cls_id}")
                    cls_name_cn = class_names_cn.get(cls_name, cls_name)
                    confidence = float(box.conf.item())
                    x1, y1, x2, y2 = box.xyxy[0].tolist()

                    detections.append({
                        "class_name": cls_name,
                        "class_name_cn": cls_name_cn,
                        "class_id": cls_id,
                        "confidence": round(confidence, 4),
                        "bbox": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                    })
                    total_objects += 1
                    display_name = cls_name_cn or cls_name
                    class_counts[display_name] = class_counts.get(display_name, 0) + 1

            inference_time = round(float(result.speed.get("inference", 0)), 2)
            artifact_dir = Path(tempfile.gettempdir()) / "rsod_agent_artifacts"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            _cleanup_agent_artifacts(artifact_dir)
            artifact_name = f"annotated_{uuid4().hex}.jpg"
            annotated_bytes = self._encode_annotated_image(result)
            (artifact_dir / artifact_name).write_bytes(annotated_bytes)
            register_artifact(artifact_name)
            logger.info("同步检测 %s: %d 个目标, 耗时 %s ms", Path(image_path).name, total_objects, inference_time)

            image_width = int(result.orig_shape[1])
            image_height = int(result.orig_shape[0])

            # ── 写入检测结果（含 MinIO 上传，匹配检测工作台的记录格式）──
            if _db and task_id:
                try:
                    minio = MinIOClient()
                    object_id = uuid4().hex
                    suffix = Path(image_path).suffix.lower() or ".jpg"
                    base_path = f"detections/{user_id}/{task_id}"
                    original_object_key = f"{base_path}/original/{object_id}{suffix}"
                    annotated_object_key = f"{base_path}/annotated/{object_id}.jpg"

                    # Upload original image to MinIO
                    try:
                        original_bytes = Path(image_path).read_bytes()
                    except OSError:
                        original_bytes = b""
                    image_url = minio.upload_bytes(original_object_key, original_bytes, "image/jpeg")
                    annotated_url = minio.upload_bytes(annotated_object_key, annotated_bytes, "image/jpeg")

                    db_results = [
                        {
                            "image_path": image_url,
                            "annotated_image_url": annotated_url,
                            "original_object_key": original_object_key,
                            "annotated_object_key": annotated_object_key,
                            "class_name": d["class_name"],
                            "class_name_cn": d.get("class_name_cn") or d["class_name"],
                            "class_id": d["class_id"],
                            "confidence": d["confidence"],
                            "bbox": d["bbox"],
                            "inference_time": inference_time,
                            "image_width": image_width,
                            "image_height": image_height,
                        }
                        for d in detections
                    ] or [
                        {
                            "image_path": image_url,
                            "annotated_image_url": annotated_url,
                            "original_object_key": original_object_key,
                            "annotated_object_key": annotated_object_key,
                            "class_name": "", "class_name_cn": None, "class_id": 0,
                            "confidence": 0.0, "bbox": [0, 0, 0, 0],
                            "inference_time": inference_time,
                            "image_width": image_width, "image_height": image_height,
                        }
                    ]
                    history_service.add_results(_db, task_id, db_results)
                    history_service.mark_completed(
                        _db, task_id, total_images=1, total_objects=total_objects,
                        total_inference_time=inference_time,
                    )
                    logger.info("Agent检测已写入结果 task_id=%s total_objects=%s", task_id, total_objects)
                except Exception:
                    logger.exception("Agent检测写入结果失败")
                    raise
        except Exception as exc:
            if _db and task_id:
                try:
                    history_service.mark_failed(_db, task_id, "Agent detection failed")
                except Exception:
                    logger.exception("Agent检测标记失败状态失败: task_id=%s", task_id)
            raise
        finally:
            if _db:
                _db.close()

        return {
            "filename": Path(image_path).name,
            "total_objects": total_objects,
            "class_counts": class_counts,
            "detections": detections,
            "inference_time": inference_time,
            "image_width": image_width,
            "image_height": image_height,
            "annotated_image_url": f"/api/agent/artifacts/{artifact_name}",
            "task_id": task_id,
        }


detection_service = DetectionService()
