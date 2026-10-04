"""
检测智能体 — ReAct Agent + 检测工具绑定

职责：
  - 创建 LangChain OpenAI Tools Agent
  - 绑定检测工具（单图/批量/ZIP）
  - 提供 chat() 和 chat_stream() 方法，支持动态切换模型

架构：
  用户消息 → Agent（LLM 决策）→ 调用 DetectionTool → 返回结果
"""
import io
import json
import os
import threading
import tempfile
import zipfile
from contextvars import ContextVar
from pathlib import Path
from typing import AsyncGenerator

from langchain_classic.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from app.config.settings import settings
from app.core.logger import get_logger
from app.core.redis_client import redis_client
from app.database.session import SessionLocal
from app.services.history_service import history_service
from app.services.detection_service import detection_service
from app.config.detection import (
    DEFAULT_VIDEO_FRAME_SAMPLE_RATE,
    DEFAULT_VIDEO_MAX_FRAMES,
    VIDEO_PROGRESS_TTL,
)

logger = get_logger(__name__)

UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "rsod_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
MAX_ZIP_FILES = 1_000
MAX_ZIP_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
_TRUSTED_BATCH_ROOT: ContextVar[Path | None] = ContextVar("trusted_batch_root", default=None)


def _safe_extract_zip(zip_path: str, target_dir: str) -> None:
    """Extract a user ZIP without allowing path traversal or zip bombs."""
    target_root = Path(target_dir).resolve()
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.infolist()
        if len(members) > MAX_ZIP_FILES:
            raise ValueError("ZIP 文件包含的条目过多")
        total_size = sum(max(0, member.file_size) for member in members)
        if total_size > MAX_ZIP_UNCOMPRESSED_BYTES:
            raise ValueError("ZIP 解压后的文件总大小不能超过 200MB")

        for member in members:
            member_path = (target_root / member.filename).resolve()
            if member_path != target_root and target_root not in member_path.parents:
                raise ValueError("ZIP 文件包含非法路径")

        for member in members:
            member_path = (target_root / member.filename).resolve()
            if member.is_dir():
                member_path.mkdir(parents=True, exist_ok=True)
                continue
            member_path.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member, "r") as source, member_path.open("wb") as target:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)


# ══════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════

def _format_detection_summary(result: dict) -> str:
    if "error" in result:
        return f"检测失败: {result['error']}"
    total = result.get("total_objects", 0)
    inference_time = result.get("inference_time", 0)
    class_counts = result.get("class_counts", {})
    count_lines = "\n".join(f"  - {name}: {count}" for name, count in class_counts.items())
    summary = f"检测完成！共检测到 {total} 个目标，推理耗时 {inference_time}ms。\n"
    if count_lines:
        summary += f"各类别统计:\n{count_lines}"
    return summary


# ══════════════════════════════════════════════════════════════
# 定义 Tool
# ══════════════════════════════════════════════════════════════

def make_detection_tools(user_id: int):
    """创建绑定到当前用户的检测工具。user_id 用于写入 DetectionTask 历史记录。"""

    @tool
    def detect_single_image(image_path: str, conf: float = 0.25, iou: float = 0.45) -> str:
        """
        检测单张图片中的目标物体。用于用户上传了一张图片并要求检测的场景。

        Args:
            image_path: 图片文件路径
            conf: 置信度阈值，取值 0~1，默认 0.25
            iou: NMS IoU 阈值，取值 0~1，默认 0.45

        Returns:
            JSON 字符串，包含 total_objects、class_counts、detections、inference_time
        """
        try:
            from app.api.agent import _validate_uploaded_image_path
            image_path = _validate_uploaded_image_path(image_path, user_id=user_id)
            result = detection_service._detect_file_sync(image_path, conf=conf, iou=iou, user_id=user_id, task_type="single")
            summary = _format_detection_summary(result)
            return json.dumps({"summary": summary, "result": result}, ensure_ascii=False)
        except Exception as exc:
            logger.exception("detect_single_image 工具异常")
            return json.dumps({"error": "Detection failed"}, ensure_ascii=False)

    @tool
    def detect_batch_images(image_paths: list[str], conf: float = 0.25) -> str:
        """
        批量检测多张图片。用于用户上传了多张图片或要求批量检测的场景。

        Args:
            image_paths: 图片文件路径列表
            conf: 置信度阈值，默认 0.25

        Returns:
            JSON 字符串，汇总各类别的检测统计
        """
        results = []
        total_objects = 0
        class_counts = {}
        for path in image_paths:
            try:
                from app.api.agent import _validate_uploaded_image_path
                trusted_root = _TRUSTED_BATCH_ROOT.get()
                if trusted_root is not None:
                    candidate = Path(path).resolve()
                    candidate.relative_to(trusted_root)
                    safe_path = str(candidate)
                else:
                    safe_path = _validate_uploaded_image_path(path, user_id=user_id)
            except Exception:
                results.append({"image": Path(path).name, "error": "File not found"})
                continue
            try:
                r = detection_service._detect_file_sync(safe_path, conf=conf, iou=0.45, user_id=user_id, task_type="batch")
                results.append({"image": Path(safe_path).name, **r})
                total_objects += r.get("total_objects", 0)
                for name, count in r.get("class_counts", {}).items():
                    class_counts[name] = class_counts.get(name, 0) + count
            except Exception as exc:
                results.append({"image": Path(safe_path).name, "error": "Detection failed"})

        return json.dumps(
            {"total_images": len(image_paths), "total_objects": total_objects,
             "class_counts": class_counts, "results": results},
            ensure_ascii=False,
        )

    @tool
    def detect_zip_images_file(zip_path: str, conf: float = 0.25) -> str:
        """
        解压 ZIP 文件并批量检测其中所有图片。
        适用于用户上传 .zip 压缩包（内含多张需要检测的图片）的场景。

        Args:
            zip_path: ZIP 文件在本地的路径
            conf: 置信度阈值，默认 0.25

        Returns:
            JSON 字符串，汇总检测结果
        """
        temp_dir = None
        try:
            from app.api.agent import _validate_uploaded_image_path
            zip_path = _validate_uploaded_image_path(zip_path, user_id=user_id)
            temp_dir = tempfile.mkdtemp(prefix="rsod_zip_")
            _safe_extract_zip(zip_path, temp_dir)

            image_files = []
            for root, _, files in os.walk(temp_dir):
                for fname in files:
                    if Path(fname).suffix.lower() in IMAGE_EXTENSIONS:
                        image_files.append(os.path.join(root, fname))

            if not image_files:
                return json.dumps({"error": "ZIP 文件内未找到图片"}, ensure_ascii=False)

            token = _TRUSTED_BATCH_ROOT.set(Path(temp_dir).resolve())
            try:
                return detect_batch_images.invoke({"image_paths": image_files, "conf": conf})
            finally:
                _TRUSTED_BATCH_ROOT.reset(token)
        except zipfile.BadZipFile:
            return json.dumps({"error": "无效的 ZIP 文件"}, ensure_ascii=False)
        except Exception as exc:
            logger.exception("detect_zip_images_file 工具异常")
            return json.dumps({"error": "ZIP detection failed"}, ensure_ascii=False)
        finally:
            if temp_dir and os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)

    @tool
    def detect_video_file(
        video_path: str,
        conf: float = 0.25,
        iou: float = 0.45,
        frame_sample_rate: int = DEFAULT_VIDEO_FRAME_SAMPLE_RATE,
        max_frames: int = DEFAULT_VIDEO_MAX_FRAMES,
    ) -> str:
        """异步检测视频附件并返回可查询的 DetectionTask。"""
        try:
            path = Path(video_path).resolve()
            user_root = (Path(UPLOAD_DIR) / str(user_id)).resolve()
            if path != user_root and user_root not in path.parents:
                raise ValueError("视频附件路径无效")
            if not path.is_file():
                raise ValueError("视频文件不存在")
            if path.suffix.lower() not in {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv"}:
                raise ValueError("不支持的视频格式")
            if not 0 <= conf <= 1 or not 0 <= iou <= 1:
                raise ValueError("conf 和 iou 必须在 0 到 1 之间")
            frame_sample_rate = max(1, min(int(frame_sample_rate), 60))
            max_frames = max(1, min(int(max_frames), DEFAULT_VIDEO_MAX_FRAMES))

            _, model_version, _ = detection_service._get_default_model()
            db = SessionLocal()
            try:
                task = history_service.create_task(
                    db, user_id=user_id, scene_id=model_version.scene_id,
                    task_type="video", model_version_id=model_version.id,
                    conf_threshold=conf, iou_threshold=iou,
                )
                history_service.mark_processing(db, task.id)
                task_id = task.id
            finally:
                db.close()

            redis_client.set_video_task(
                task_id,
                {"status": "processing", "progress": 0, "message": "视频检测处理中"},
                ttl=VIDEO_PROGRESS_TTL,
            )

            def update_progress(current_frame, total_frames):
                progress = round(current_frame / total_frames * 100, 2) if total_frames else 0
                redis_client.set_video_task(
                    task_id,
                    {
                        "status": "processing", "progress": progress,
                        "current_frame": current_frame, "total_frames": total_frames,
                        "message": "视频检测处理中",
                    },
                    ttl=VIDEO_PROGRESS_TTL,
                )

            def run_detection():
                try:
                    result = detection_service.detect_video(
                        video_path=str(path), model_id=model_version.id, task_id=task_id,
                        conf=conf, iou=iou, frame_sample_rate=frame_sample_rate,
                        max_frames=max_frames, progress_callback=update_progress,
                    )
                    redis_client.set_video_task(
                        task_id,
                        {"status": "completed", "progress": 100, "message": "视频检测完成", "result": result},
                        ttl=VIDEO_PROGRESS_TTL,
                    )
                except Exception:
                    logger.exception("Agent 视频检测失败 task_id=%s", task_id)
                    redis_client.set_video_task(
                        task_id,
                        {"status": "failed", "progress": 0, "message": "视频检测失败"},
                        ttl=VIDEO_PROGRESS_TTL,
                    )
                finally:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        logger.warning("Agent 视频临时文件清理失败 task_id=%s", task_id)

            threading.Thread(target=run_detection, daemon=True, name=f"agent-video-{task_id}").start()
            return json.dumps(
                {"task_id": task_id, "status": "processing", "message": "视频检测任务已创建，可通过任务 ID 查询进度"},
                ensure_ascii=False,
            )
        except Exception as exc:
            logger.exception("detect_video_file 工具异常")
            return json.dumps({"error": "视频检测任务创建失败"}, ensure_ascii=False)

    return [detect_single_image, detect_batch_images, detect_zip_images_file, detect_video_file]


# 向后兼容：无 user_id 时的默认工具列表（不写 DB）
DETECTION_TOOLS = make_detection_tools(None)


# ══════════════════════════════════════════════════════════════
# LLM 工厂
# ══════════════════════════════════════════════════════════════

def _make_llm(model: str | None = None):
    """根据 settings 创建 ChatOpenAI 实例。

    Args:
        model: 前端选择的模型名，若为 None 则使用 .env 默认值
    """
    api_key = settings.OPENAI_API_KEY
    base_url = settings.OPENAI_BASE_URL

    if not api_key:
        raise RuntimeError("未配置 OPENAI_API_KEY")

    model_name = model or settings.OPENAI_MODEL
    logger.info("Agent LLM: model=%s base_url=%s", model_name, base_url)
    return ChatOpenAI(
        model=model_name,
        openai_api_key=api_key,
        openai_api_base=base_url,
        temperature=0.1,
    )


def _make_executor(llm):
    """用指定 LLM 创建 AgentExecutor"""
    prompt = ChatPromptTemplate.from_messages([
        ("system", _SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="chat_history", optional=True),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])
    agent = create_openai_tools_agent(llm=llm, tools=DETECTION_TOOLS, prompt=prompt)
    return AgentExecutor(
        agent=agent,
        tools=DETECTION_TOOLS,
        verbose=True,
        max_iterations=5,
        return_intermediate_steps=True,
    )


_SYSTEM_PROMPT = """你是一个专业的目标检测助手，可以帮助用户检测图片中的目标物体。

重要规则：
- 当用户消息中包含 [附件图片路径: xxx] 时，xxx 就是服务端的图片路径，你必须直接使用它调用检测工具
- 不要要求用户再次提供路径，直接使用附件中给出的路径
- 单张图片 → 调用 detect_single_image
- 多张图片 → 调用 detect_batch_images
- ZIP 压缩包 → 调用 detect_zip_images_file
- 视频附件 → 调用 detect_video_file；工具会立即返回 task_id，告知用户可在任务中心查看进度

工作流程：
1. 理解用户意图
2. 调用对应检测工具
3. 用自然语言总结检测结果

回复要求：
- 先报告检测到的目标总数
- 列出各类别数量统计
- 简洁专业，使用中文，不要输出emoji"""


class DetectionAgent:
    """检测智能体"""

    def __init__(self):
        self._default_llm = None
        self._default_executor = None
        logger.info("DetectionAgent 初始化完成，绑定 %d 个工具", len(DETECTION_TOOLS))

    @property
    def default_executor(self):
        if self._default_executor is None:
            self._default_llm = _make_llm()
            self._default_executor = _make_executor(self._default_llm)
        return self._default_executor

    def _get_executor(self, model: str | None):
        """根据模型名获取 executor。model=None 时使用默认。"""
        if model is None:
            return self.default_executor
        llm = _make_llm(model)
        return _make_executor(llm)

    async def chat(self, message: str, image_paths: list[str] = None, model: str = None, chat_history: list[dict] | None = None) -> dict:
        if image_paths:
            paths_text = "\n".join(f"[附件图片路径: {p}]" for p in image_paths)
            message = f"{message}\n{paths_text}"
        try:
            executor = self._get_executor(model)
            result = await executor.ainvoke({"input": message, "chat_history": chat_history or []})
            return {
                "output": result["output"],
                "intermediate_steps": result.get("intermediate_steps", []),
            }
        except Exception as exc:
            logger.exception("Agent 执行异常")
            return {"output": "处理出错，请稍后重试。", "intermediate_steps": []}

    async def chat_stream(self, message: str, image_paths: list[str] = None, model: str = None, chat_history: list[dict] | None = None) -> AsyncGenerator:
        if image_paths:
            paths_text = "\n".join(f"[附件图片路径: {p}]" for p in image_paths)
            message = f"{message}\n{paths_text}"

        executor = self._get_executor(model)
        try:
            async for event in executor.astream_events(
                {"input": message, "chat_history": chat_history or []}, version="v2"
            ):
                kind = event["event"]

                if kind == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    if hasattr(chunk, "content") and chunk.content:
                        yield {"type": "text_chunk", "content": chunk.content}

                elif kind == "on_tool_start":
                    yield {
                        "type": "tool_call",
                        "tool": event["name"],
                        "input": event["data"].get("input", {}),
                    }

                elif kind == "on_tool_end":
                    output = event["data"].get("output", "")
                    yield {
                        "type": "tool_result",
                        "tool": event.get("name", ""),
                        "result": str(output) if output else "",
                    }

        except Exception as exc:
            logger.exception("Agent 流式执行异常")
            yield {"type": "error", "content": "处理出错，请稍后重试。"}


detection_agent = DetectionAgent()
