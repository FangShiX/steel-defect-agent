"""Agent chat API — streaming chat, model listing, and image upload."""

import asyncio
import json
import os
import tempfile
import time
from urllib.parse import urlparse
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agent.supervisor import supervisor_agent
from app.agent.state import AGENT_LABELS
from app.api.auth import get_current_user
from app.config.settings import settings
from app.core.artifact_access import artifact_owner_id, can_read_artifact, unregister_artifact
from app.core.logger import get_logger
from app.database.session import SessionLocal, get_db
from app.entity.db_models import ChatMessage, ChatSession
from app.services.action_confirmation_service import action_confirmation_service
from app.services.operation_log_service import operation_log_service

router = APIRouter(prefix="/api/agent", tags=["智能体"])
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/bmp", "image/tiff", "image/webp"}
ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}

logger = get_logger(__name__)
MAX_HISTORY_MESSAGES = 20


class AgentSessionUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    archived: Optional[bool] = None


def _card_type_for_tool(tool_name: str) -> str:
    if tool_name.startswith("detect_"):
        return "detection_result"
    if tool_name == "get_detection_statistics":
        return "statistics"
    if tool_name == "query_detection_history":
        return "history"
    if tool_name == "search_knowledge":
        return "knowledge_citations"
    return "tool_result"


def _card_references(result: Any) -> dict[str, list[int]]:
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            return {}
    result = (result or {}).get("result", result) if isinstance(result, dict) else {}
    if not isinstance(result, dict):
        return {}
    references = {}
    for source, target in (("task_id", "task_ids"), ("model_id", "model_ids"), ("file_id", "file_ids"), ("knowledge_document_id", "knowledge_document_ids")):
        value = result.get(source)
        if isinstance(value, int):
            references[target] = [value]
    knowledge_ids = {
        item.get("document_id")
        for item in result.get("results", [])
        if isinstance(item, dict) and isinstance(item.get("document_id"), int)
    }
    if knowledge_ids:
        references["knowledge_document_ids"] = sorted(knowledge_ids)
    return references


def _tool_task_ids(tool_calls: list[dict]) -> list[str]:
    ids = set()
    for tool_call in tool_calls:
        for task_id in (tool_call.get("references") or {}).get("task_ids", []):
            ids.add(str(task_id))
    return sorted(ids)


_SENSITIVE_TOOL_KEYS = {"password", "token", "authorization", "api_key", "secret", "query", "prompt", "text", "body", "reply", "file_content"}


def _sanitize_tool_value(value: Any, key: str = "") -> Any:
    """Keep durable tool traces useful without storing secrets or private payloads."""
    if key.lower() in _SENSITIVE_TOOL_KEYS:
        return "[redacted]"
    if key.lower() in {"content", "query", "prompt", "text", "body", "reply", "file_content"} and isinstance(value, str):
        return "[private-content-redacted]"
    if isinstance(value, dict):
        return {item_key: _sanitize_tool_value(item, item_key) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_tool_value(item, key) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            return json.dumps(_sanitize_tool_value(parsed), ensure_ascii=False)
        if value.startswith("/api/agent/artifacts/"):
            return value
        parsed = urlparse(value)
        if parsed.scheme in {"http", "https"}:
            return f"[signed-resource:{parsed.path.rsplit('/', 1)[-1]}]"
        if key in {"path", "image_path", "file_path", "image", "url"}:
            return f"[private-path:{Path(value).name}]"
        return value
    return value


def _sanitize_tool_calls(tool_calls: list[dict] | None) -> list[dict] | None:
    return _sanitize_tool_value(tool_calls) if tool_calls else tool_calls

# ── in-process cache for model list ──
_model_cache: dict[str, Any] | None = None
_model_cache_ts: float = 0.0
_MODEL_CACHE_TTL: float = 300

UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "rsod_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
ARTIFACT_DIR = os.path.join(tempfile.gettempdir(), "rsod_agent_artifacts")
os.makedirs(ARTIFACT_DIR, exist_ok=True)


def _user_upload_dir(user_id: int) -> Path:
    """Return the per-user directory used for unpersisted chat attachments."""
    directory = Path(UPLOAD_DIR) / str(user_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _new_upload_path(user_id: int, suffix: str) -> Path:
    return _user_upload_dir(user_id) / f"{uuid4().hex}{suffix}"


def _cleanup_attachment_errors(func):
    def wrapped(upload, user_id: int, tracked_paths: list[str] | None = None):
        try:
            return func(upload, user_id, tracked_paths)
        except Exception:
            if tracked_paths:
                _cleanup_uploaded_paths(tracked_paths, user_id)
            raise
    return wrapped


@_cleanup_attachment_errors
def _save_attachment(upload, user_id: int, tracked_paths: list[str] | None = None) -> tuple[str, dict]:
    """Store a chat attachment safely; its type is used only for routing."""
    filename = Path(upload.filename or "attachment").name
    if not filename or "\x00" in filename or any(ord(ch) < 32 for ch in filename):
        raise HTTPException(status_code=400, detail="文件名无效")
    content = upload.file.read(MAX_ATTACHMENT_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="附件不能为空")
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="附件大小不能超过 50MB")
    suffix = Path(filename).suffix.lower()
    filepath = _new_upload_path(user_id, suffix)
    try:
        filepath.write_bytes(content)
    except Exception:
        if tracked_paths:
            _cleanup_uploaded_paths(tracked_paths, user_id)
        raise
    if tracked_paths is not None:
        tracked_paths.append(str(filepath))
    return str(filepath), {
        "name": filename,
        "path": str(filepath),
        "content_type": upload.content_type or "application/octet-stream",
        "suffix": suffix,
        "size": len(content),
    }


def _cleanup_uploaded_paths(paths: list[str], user_id: int) -> None:
    for path in {item for item in paths if item}:
        try:
            os.unlink(_validate_uploaded_image_path(path, user_id=user_id))
        except (FileNotFoundError, HTTPException, OSError):
            pass


def _artifact_filenames(tool_calls: list[dict] | None) -> set[str]:
    """Extract only opaque Agent artifact names from persisted tool payloads."""
    filenames: set[str] = set()

    def visit(value):
        if isinstance(value, str):
            try:
                visit(json.loads(value))
            except json.JSONDecodeError:
                prefix = "/api/agent/artifacts/"
                if value.startswith(prefix):
                    filename = Path(value[len(prefix):]).name
                    if filename.startswith("annotated_") and filename.endswith(".jpg"):
                        filenames.add(filename)
        elif isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(tool_calls or [])
    return filenames


def _artifact_referenced_by_user(db: Session, filename: str, current_user) -> bool:
    """Recover persisted artifact access after a process restart.

    The in-process ownership map is intentionally fast, but it is not durable.
    ChatMessage.tool_calls is the durable association between an artifact and
    its session owner, so use it as the fallback authorization source.
    """
    # Keeping this guard makes direct unit calls to the route helper behave
    # like the injected route (where FastAPI always supplies a Session).
    if not hasattr(db, "query"):
        return False
    query = db.query(ChatMessage).join(ChatSession, ChatMessage.session_id == ChatSession.id)
    if not current_user.is_superuser:
        query = query.filter(ChatSession.user_id == current_user.id)
    for message in query.all():
        if filename in _artifact_filenames(message.tool_calls):
            return True
    return False


# ══════════════════════════════════════════════════════════════
# Model listing
# ══════════════════════════════════════════════════════════════

@router.get("/models")
async def list_models():
    global _model_cache, _model_cache_ts
    now = time.time()
    if _model_cache is not None and (now - _model_cache_ts) < _MODEL_CACHE_TTL:
        return _model_cache

    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="未配置 OPENAI_API_KEY")

    url = f"{settings.OPENAI_BASE_URL.rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="获取模型列表超时")
    except httpx.HTTPStatusError as exc:
        logger.warning("Model list fetch failed — status=%s", exc.response.status_code)
        raise HTTPException(status_code=502, detail=f"获取模型列表失败 (HTTP {exc.response.status_code})")
    except httpx.HTTPError as exc:
        logger.warning("Model list fetch failed: %s", exc)
        raise HTTPException(status_code=502, detail="获取模型列表失败，请稍后重试") from exc

    raw_models: list[dict] = data.get("data", [])
    seen: set[str] = set()
    models: list[dict] = []
    for m in raw_models:
        mid = m.get("id", "")
        if not mid or mid in seen:
            continue
        seen.add(mid)
        models.append({"id": mid, "owned_by": m.get("owned_by", "unknown")})

    preferred = {"qwen3.7-plus", "qwen-plus", "qwen-max", "deepseek-v4-pro"}
    models.sort(key=lambda m: (m["id"] not in preferred, m["id"]))

    _model_cache = {"models": models, "provider": url}
    _model_cache_ts = now
    return _model_cache


@router.get("/models/cached")
async def cached_models():
    if _model_cache is None:
        return {"models": [], "provider": None}
    return _model_cache


# @internal-compat: read-only fallback for deployments without chat CRUD.
@router.get("/sessions", include_in_schema=False)
def list_chat_sessions(
    search: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    archived: bool | None = None,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the user's sessions, or every user's sessions for administrators."""
    if search is not None and len(search) > 200:
        raise HTTPException(status_code=422, detail="Search query is too long")
    if page is not None and page < 1:
        raise HTTPException(status_code=422, detail="Page must be at least 1")
    if page_size is not None and not 1 <= page_size <= 100:
        raise HTTPException(status_code=422, detail="Page size must be between 1 and 100")
    query = db.query(ChatSession)
    if not current_user.is_superuser:
        query = query.filter(ChatSession.user_id == current_user.id)
    if archived is not None:
        query = query.filter(ChatSession.status == ("archived" if archived else "active"))
    if search:
        query = query.filter(ChatSession.title.ilike(f"%{search.strip()}%"))
    query = query.order_by(
        ChatSession.last_message_at.desc(), ChatSession.created_at.desc()
    )
    total = query.count()
    if page is not None and page_size is not None:
        query = query.offset((page - 1) * page_size).limit(page_size)
    sessions = query.all()
    items = [
        {
            "id": session.session_uuid,
            "owner_id": session.user_id,
            "owner_username": session.user.username if session.user else "",
            "title": session.title or "新对话",
            "message_count": session.message_count or 0,
            "created_at": session.created_at,
            "updated_at": session.last_message_at or session.created_at,
            "archived": session.status == "archived",
        }
        for session in sessions
    ]
    if page is None and page_size is None and search is None and archived is None:
        return items
    return {"items": items, "total": total, "page": page or 1, "page_size": page_size or total}


def _get_owned_session(db: Session, session_id: str, user_id: int) -> ChatSession | None:
    """Resolve a globally unique session UUID and enforce its owner."""
    session = db.query(ChatSession).filter(ChatSession.session_uuid == session_id).first()
    if session is not None and session.user_id != user_id:
        raise HTTPException(status_code=409, detail="会话标识已属于其他用户，请创建新会话")
    if session is not None and session.status == "deleted":
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


def _get_visible_session(db: Session, session_id: str, current_user) -> ChatSession:
    """Resolve a session visible to its owner or to an administrator."""
    query = db.query(ChatSession).filter(ChatSession.session_uuid == session_id)
    if not current_user.is_superuser:
        query = query.filter(ChatSession.user_id == current_user.id)
    session = query.first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.status == "deleted":
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


# @internal-compat: legacy session detail; frontend uses /api/chat/sessions.
@router.get("/sessions/{session_id}", include_in_schema=False)
def get_chat_session(
    session_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return a session to its owner or to an administrator."""
    session = _get_visible_session(db, session_id, current_user)
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .all()
    )
    return {
        "id": session.session_uuid,
        "owner_id": session.user_id,
        "owner_username": session.user.username if session.user else "",
        "title": session.title or "新对话",
        "message_count": session.message_count or 0,
        "created_at": session.created_at,
        "updated_at": session.last_message_at or session.created_at,
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "has_image": bool(message.image_paths or message.image_path),
                "attachments": [
                    {key: item.get(key) for key in ("name", "content_type", "size") if item.get(key) is not None}
                    for item in (message.attachments or [])
                ],
                "image_urls": [f"/api/agent/sessions/{session_id}/messages/{message.id}/image?index={index}" for index, _ in enumerate(message.image_paths or ([message.image_path] if message.image_path else []))],
                "tool_calls": message.tool_calls or [],
                "created_at": message.created_at,
            }
            for message in messages
        ],
    }


@router.patch("/sessions/{session_id}")
def update_chat_session(
    session_id: str,
    payload: AgentSessionUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update owner-controlled session metadata without changing messages."""
    session = _get_owned_session(db, session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session does not exist")
    if payload.title is not None:
        title = payload.title.strip()
        if not title:
            raise HTTPException(status_code=422, detail="Session title cannot be empty")
        session.title = title
    if payload.archived is not None:
        session.status = "archived" if payload.archived else "active"
    session.updated_at = datetime.now()
    db.commit()
    db.refresh(session)
    return {
        "id": session.session_uuid,
        "title": session.title or "New chat",
        "archived": session.status == "archived",
        "updated_at": session.updated_at,
    }


@router.get("/sessions/{session_id}/messages/{message_id}/image")
def get_chat_message_image(
    session_id: str,
    message_id: int,
    index: int = 0,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Serve a persisted attachment to its owner or to an administrator."""
    session = _get_visible_session(db, session_id, current_user)
    message = db.query(ChatMessage).filter(
        ChatMessage.session_id == session.id,
        ChatMessage.id == message_id,
    ).first()
    if not message:
        raise HTTPException(status_code=404, detail="图片不存在")
    image_paths = message.image_paths or ([message.image_path] if message.image_path else [])
    if index < 0 or index >= len(image_paths):
        raise HTTPException(status_code=404, detail="图片不存在")
    image_path = _validate_uploaded_image_path(image_paths[index])
    return FileResponse(image_path)


@router.get("/sessions/{session_id}/messages/{message_id}/attachment")
def get_chat_message_attachment(
    session_id: str,
    message_id: int,
    index: int = 0,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Serve any persisted chat attachment, including video files."""
    session = _get_visible_session(db, session_id, current_user)
    message = db.query(ChatMessage).filter(ChatMessage.session_id == session.id, ChatMessage.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Attachment not found")
    attachments = message.attachments or []
    paths = [item.get("path") for item in attachments if item.get("path")]
    if index < 0 or index >= len(paths):
        raise HTTPException(status_code=404, detail="Attachment not found")
    path = paths[index]
    safe_path = _validate_uploaded_image_path(path, user_id=current_user.id)
    media_type = next((item.get("content_type") for item in attachments if item.get("path") == path), None)
    return FileResponse(safe_path, media_type=media_type)


# @internal-compat: legacy hard-delete endpoint retained for older clients;
# frontend consumers use the canonical /api/chat/sessions endpoint, which
# soft-deletes and supports undo. Keep this route out of generated API docs.
@router.delete("/sessions/{session_id}", include_in_schema=False)
def delete_chat_session(
    session_id: str,
    confirmation_id: str | None = Header(default=None, alias="X-Confirmation-ID"),
    request: Request = None,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a persisted session only as its owner.

    Administrators may review other users' sessions, but reviewing must not
    grant destructive access to another user's conversation.
    """
    if not isinstance(confirmation_id, str):
        confirmation_id = None
    session = _get_owned_session(db, session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    action_confirmation_service.require_or_prepare(
        db, confirmation_uuid=confirmation_id, user_id=current_user.id,
        operation="delete_chat_session", target_type="chat_session", target_id=session_id,
        impact={"scope": "conversation messages, attachments, and generated artifacts", "reversible": False},
        payload={"session_id": session_id},
        request_id=getattr(getattr(request, "state", None), "request_id", None),
    )
    image_paths = []
    attachment_paths = []
    artifact_filenames = set()
    for message in db.query(ChatMessage).filter(ChatMessage.session_id == session.id).all():
        image_paths.extend(message.image_paths or ([message.image_path] if message.image_path else []))
        attachment_paths.extend(item.get("path") for item in (message.attachments or []) if item.get("path"))
        artifact_filenames.update(_artifact_filenames(message.tool_calls))
    db.query(ChatMessage).filter(ChatMessage.session_id == session.id).delete(
        synchronize_session=False
    )
    db.delete(session)
    db.commit()
    operation_log_service.record(
        db, user=current_user, module="agent", action="delete_chat_session",
        target_type="chat_session", target_id=session_id,
        description=f"Delete chat session {session_id}", request=request,
    )
    for image_path in image_paths:
        try:
            os.unlink(_validate_uploaded_image_path(image_path, user_id=current_user.id))
        except (FileNotFoundError, HTTPException, OSError):
            pass
    for attachment_path in attachment_paths:
        try:
            os.unlink(_validate_uploaded_image_path(attachment_path, user_id=current_user.id))
        except (FileNotFoundError, HTTPException, OSError):
            pass
    for filename in artifact_filenames:
        artifact_path = (Path(ARTIFACT_DIR) / filename).resolve()
        if artifact_path.parent == Path(ARTIFACT_DIR).resolve():
            try:
                artifact_path.unlink(missing_ok=True)
            except OSError:
                pass
        unregister_artifact(filename)
    return {"id": session_id, "message": "会话已删除"}


# ══════════════════════════════════════════════════════════════
# @internal-compat: legacy image-only upload kept for older clients; ChatPage
# uses /chat/stream attachments so new files do not pass through this endpoint.
# ══════════════════════════════════════════════════════════════

@router.post("/runs/{run_id}/cancel")
def cancel_agent_run(run_id: str, current_user=Depends(get_current_user)):
    raise HTTPException(status_code=501, detail="Agent run remote cancellation is not implemented")


@router.post("/runs/{run_id}/tools/{tool_call_id}/cancel")
def cancel_agent_tool(run_id: str, tool_call_id: str, current_user=Depends(get_current_user)):
    raise HTTPException(status_code=501, detail="Agent tool remote cancellation is not implemented")


@router.post("/upload", include_in_schema=False)
async def upload_image(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
):
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="仅支持图片文件")
    suffix = Path(file.filename).suffix.lower() or ".jpg"
    filepath = _new_upload_path(current_user.id, suffix)
    content = await file.read(MAX_IMAGE_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="图片不能为空")
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="图片大小不能超过 10MB")
    with open(filepath, "wb") as f:
        f.write(content)
    logger.info("图片上传成功: %s → %s", file.filename, filepath)
    return {"image_path": str(filepath)}


# Protected artifact endpoint consumed by the chat result renderer.
@router.get("/artifacts/{filename}")
def get_agent_artifact(
    filename: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Serve an opaque, generated detection artifact for inline chat previews."""
    safe_name = Path(filename).name
    if safe_name != filename or not safe_name.startswith("annotated_") or not safe_name.endswith(".jpg"):
        raise HTTPException(status_code=404, detail="检测结果图片不存在")
    if not can_read_artifact(safe_name, current_user.id, current_user.is_superuser) and not _artifact_referenced_by_user(db, safe_name, current_user):
        raise HTTPException(status_code=404, detail="Artifact not found")
    artifact_path = (Path(ARTIFACT_DIR) / safe_name).resolve()
    if artifact_path.parent != Path(ARTIFACT_DIR).resolve() or not artifact_path.is_file():
        raise HTTPException(status_code=404, detail="检测结果图片不存在")
    return FileResponse(artifact_path, media_type="image/jpeg")


# ══════════════════════════════════════════════════════════════
# SSE streaming chat
# ══════════════════════════════════════════════════════════════

@router.post("/chat/stream")
async def chat_stream(
    request: Request,
    _current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """SSE 流式对话 — Agent 智能回复。

    支持两种请求格式：
    - FormData: message, session_id, model (前端 uses FormData)
    - JSON: {"message": "...", "session_id": "...", "model": "...", "image_path": "..."}
    """
    content_type = request.headers.get("content-type", "")

    message = ""
    image_paths = []
    image_path = None
    model = None
    session_id = None
    attachments = []
    tracked_attachment_paths = []

    if "multipart/form-data" in content_type:
        form = await request.form()
        message = form.get("message", "")
        if isinstance(message, str):
            message = message.strip()
        raw_model = form.get("model")
        if raw_model and isinstance(raw_model, str) and raw_model.strip():
            model = raw_model.strip()
        raw_session = form.get("session_id")
        if raw_session and isinstance(raw_session, str) and raw_session.strip():
            session_id = raw_session.strip()
        image_paths = []
        for upload in form.getlist("attachment"):
            if upload is not None and hasattr(upload, "filename") and upload.filename:
                path, metadata = _save_attachment(
                    upload, _current_user.id, tracked_attachment_paths,
                )
                attachments.append(metadata)
                if (
                    metadata["content_type"] in ALLOWED_IMAGE_TYPES
                    or metadata["suffix"] in ALLOWED_IMAGE_SUFFIXES
                ):
                    image_paths.append(path)
        image_files = form.getlist("image")
        for image_file in image_files:
            if image_file is not None and hasattr(image_file, "filename") and image_file.filename:
                if image_file.content_type not in ALLOWED_IMAGE_TYPES and image_file.content_type:
                    raise HTTPException(status_code=415, detail="仅支持 JPG、PNG、BMP、TIFF、WebP 图片")
                content = await image_file.read(MAX_IMAGE_BYTES + 1)
                if len(content) > MAX_IMAGE_BYTES:
                    raise HTTPException(status_code=413, detail="图片大小不能超过 10MB")
                suffix = Path(image_file.filename).suffix.lower() or ".jpg"
                filepath = _new_upload_path(_current_user.id, suffix)
                with open(filepath, "wb") as f:
                    f.write(content)
                image_paths.append(str(filepath))
                attachments.append({"name": Path(image_file.filename).name, "path": str(filepath), "content_type": image_file.content_type or "image/*", "suffix": suffix})
        if image_paths:
            image_path = image_paths[0]
    else:
        body = await request.json()
        message = (body.get("message") or "").strip()
        raw_model = body.get("model")
        if raw_model and isinstance(raw_model, str) and raw_model.strip():
            model = raw_model.strip()
        raw_session = body.get("session_id")
        if raw_session and isinstance(raw_session, str) and raw_session.strip():
            session_id = raw_session.strip()
        raw_image_path = body.get("image_path")
        if raw_image_path:
            image_paths = [_validate_uploaded_image_path(raw_image_path, user_id=_current_user.id)]
            attachments = [{"name": Path(raw_image_path).name, "path": image_paths[0], "content_type": "image/*", "suffix": Path(raw_image_path).suffix.lower()}]

    if not message and not image_paths and not attachments:
        raise HTTPException(status_code=422, detail="消息不能为空")

    logger.info("Agent chat: message_len=%d attachments=%d model=%s session=%s", len(message), len(attachments), model or "default", session_id or "new")

    user_id = _current_user.id
    request_state = getattr(request, "state", None)
    request_id = getattr(request_state, "request_id", None)
    if request_state is not None:
        request_state.session_id = session_id

    # Validate ownership before starting the SSE response so a stale UUID from
    # another signed-in user becomes a normal HTTP 409 instead of an INSERT error.
    if session_id:
        try:
            _get_owned_session(db, session_id, user_id)
        except Exception:
            _cleanup_uploaded_paths(
                image_paths + [item.get("path") for item in attachments], user_id,
            )
            raise

    # ── load chat history ──
    history = _load_history(session_id, user_id) if session_id else []

    async def event_generator():
        full_reply = ""
        tool_calls = []
        persisted = False
        stream_failed = False
        audit_logged = False
        owner_token = artifact_owner_id.set(user_id)
        try:
            async for event in supervisor_agent.chat_stream(
                message=message, image_paths=image_paths or None, attachments=attachments, model=model, chat_history=history, user_id=user_id
            ):
                if event.get("type") == "text_chunk":
                    full_reply += event.get("content", "")
                event_type = event.get("type", "")
                if event_type == "text_chunk":
                    yield f"data: {json.dumps({'type': 'text_delta', 'content': event['content']}, ensure_ascii=False)}\n\n"
                elif event_type == "agent_switch":
                    yield f"data: {json.dumps({'type': 'agent_switch', 'agent': event['agent'], 'label': event['label']}, ensure_ascii=False)}\n\n"
                elif event_type == "tool_call":
                    tool_agent = event.get("agent", "")
                    tool_call = {
                        "id": uuid4().hex,
                        "name": event["tool"],
                        "status": "running",
                        "input": event.get("input", {}),
                        "card_type": _card_type_for_tool(event["tool"]),
                        "display_order": len(tool_calls),
                        "created_at": datetime.now().isoformat(),
                        "agent": tool_agent,
                        "agentLabel": AGENT_LABELS.get(tool_agent, ""),
                    }
                    tool_calls.append(tool_call)
                    yield f"data: {json.dumps({'type': 'tool_start', 'tool_call_id': tool_call['id'], 'tool_name': event['tool'], 'input': event.get('input', {}), 'agent': event.get('agent', ''), 'request_id': request_id, 'session_id': session_id, 'user_id': user_id}, ensure_ascii=False)}\n\n"
                elif event_type == "tool_result":
                    references = _card_references(event["result"])
                    for tool_call in reversed(tool_calls):
                        if tool_call["name"] == event["tool"]:
                            tool_call.update({
                                "status": "success",
                                "result": event["result"],
                                "payload": event["result"],
                                "references": references,
                                "snapshot": {"tool": event["tool"], "completed_at": datetime.now().isoformat()},
                            })
                            tool_call_id = tool_call["id"]
                            break
                    else:
                        tool_call_id = None
                    yield f"data: {json.dumps({'type': 'tool_result', 'tool_call_id': tool_call_id, 'tool_name': event['tool'], 'result': event['result'], 'references': references, 'task_ids': references.get('task_ids', []), 'agent': event.get('agent', ''), 'request_id': request_id, 'session_id': session_id, 'user_id': user_id}, ensure_ascii=False)}\n\n"
                elif event_type == "error":
                    stream_failed = True
                    error_code = event.get("code", "AGENT_EXECUTION_FAILED")
                    error_message = event.get("message") or "Agent execution failed"
                    status_code = int(event.get("status_code", 502))
                    retryable = bool(event.get("retryable", status_code in {408, 425, 429, 500, 502, 503, 504}))
                    task_ids = _tool_task_ids(tool_calls)
                    yield f"data: {json.dumps({'type': 'error', 'code': error_code, 'error_code': error_code, 'status_code': status_code, 'message': error_message, 'detail': {'code': error_code, 'message': error_message}, 'request_id': request_id, 'task_id': task_ids[0] if task_ids else None, 'session_id': session_id, 'user_id': user_id, 'retryable': retryable}, ensure_ascii=False)}\n\n"

            # ── save to history ──
            if session_id and (message or full_reply):
                _save_message(session_id, user_id, "user", message, image_paths=image_paths, image_path=image_path, attachments=attachments)
                _save_message(session_id, user_id, "assistant", full_reply, tool_calls=tool_calls)
                persisted = True

            task_ids = _tool_task_ids(tool_calls)
            if request_state is not None:
                request_state.task_id = task_ids[0] if task_ids else None
            operation_log_service.record(
                db, user=_current_user, module="agent", action="chat",
                target_type="chat_session", target_id=session_id,
                description="Agent chat completed", status="failure" if stream_failed else "success",
                request=request, task_id=task_ids[0] if task_ids else None,
                session_id=session_id,
            )
            audit_logged = True
            yield f"data: {json.dumps({'type': 'message_end', 'request_id': request_id, 'session_id': session_id, 'user_id': user_id, 'task_ids': task_ids}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except asyncio.CancelledError:
            if session_id and not persisted:
                _save_message(session_id, user_id, "user", message, image_paths=image_paths, image_path=image_path, attachments=attachments)
                _save_message(session_id, user_id, "assistant", full_reply, tool_calls=tool_calls)
                persisted = True
            logger.info("SSE stream cancelled session=%s user_id=%s", session_id, user_id)
            raise
        except Exception as exc:
            if session_id and not persisted:
                _save_message(session_id, user_id, "user", message, image_paths=image_paths, image_path=image_path, attachments=attachments)
                _save_message(session_id, user_id, "assistant", full_reply, tool_calls=tool_calls)
                persisted = True
            logger.exception("SSE 流异常")
            if not audit_logged:
                operation_log_service.record(
                    db, user=_current_user, module="agent", action="chat",
                    target_type="chat_session", target_id=session_id,
                    description="Agent chat failed", status="failure",
                    request=request, task_id=(_tool_task_ids(tool_calls) or [None])[0],
                    session_id=session_id,
                )
            error_payload = {
                "type": "error",
                "code": "AGENT_STREAM_FAILED",
                "error_code": "AGENT_STREAM_FAILED",
                "status_code": 502,
                "message": "Agent stream failed",
                "detail": {"code": "AGENT_STREAM_FAILED", "message": "Agent stream failed"},
                "request_id": request_id,
                "task_id": (_tool_task_ids(tool_calls) or [None])[0],
                "session_id": session_id,
                "user_id": user_id,
                "retryable": True,
            }
            yield f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"
        finally:
            if not persisted:
                _cleanup_uploaded_paths(
                    image_paths + [item.get("path") for item in attachments], user_id,
                )
            artifact_owner_id.reset(owner_token)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Request-ID": request_id or "",
        },
    )


# ══════════════════════════════════════════════════════════════
# Session history helpers
# ══════════════════════════════════════════════════════════════

def _ensure_session(session_id: str, user_id: int):
    db = SessionLocal()
    try:
        s = _get_owned_session(db, session_id, user_id)
        if not s:
            s = ChatSession(session_uuid=session_id, user_id=user_id, title="")
            db.add(s)
            db.commit()
            db.refresh(s)
        return s
    finally:
        db.close()


def _validate_uploaded_image_path(image_path: str, user_id: int | None = None) -> str:
    if not isinstance(image_path, str) or not image_path.strip():
        raise HTTPException(status_code=400, detail="图片路径无效")
    candidate = Path(image_path).resolve()
    upload_root = Path(UPLOAD_DIR).resolve()
    try:
        candidate.relative_to(upload_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="图片路径无效") from exc
    if user_id is not None:
        try:
            candidate.relative_to(_user_upload_dir(user_id).resolve())
        except ValueError as exc:
            raise HTTPException(status_code=403, detail="无权访问该图片") from exc
    if not candidate.is_file():
        raise HTTPException(status_code=400, detail="图片文件不存在")
    return str(candidate)


def _load_history(session_id: str, user_id: int | None = None) -> list[dict]:
    """加载最近的对话历史，转为 LangChain 消息格式"""
    db = SessionLocal()
    try:
        query = db.query(ChatSession).filter(ChatSession.session_uuid == session_id)
        if user_id is not None:
            query = query.filter(ChatSession.user_id == user_id)
        s = query.first()
        if not s:
            return []
        messages = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == s.id)
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(MAX_HISTORY_MESSAGES)
            .all()
        )
        messages.reverse()
        history = []
        for m in messages:
            if m.role in ("user", "assistant"):
                content = m.content or ""
                if m.role == "user":
                    valid_paths = []
                    for image_path in m.image_paths or ([m.image_path] if m.image_path else []):
                        try:
                            valid_paths.append(_validate_uploaded_image_path(image_path, user_id=user_id))
                        except HTTPException:
                            pass
                    if valid_paths:
                        content = f"{content}\n" + "\n".join(f"[附件图片路径: {path}]" for path in valid_paths)
                if m.role == "user":
                    for attachment in m.attachments or []:
                        try:
                            path = _validate_uploaded_image_path(attachment.get("path"), user_id=user_id)
                        except (HTTPException, AttributeError):
                            continue
                        content += f"\n[attachment: {attachment.get('name', Path(path).name)} | type: {attachment.get('content_type', '')} | path: {path}]"
                history.append({"role": m.role, "content": content})
        return history
    finally:
        db.close()


def _save_message(
    session_id: str,
    user_id: int,
    role: str,
    content: str,
    image_paths: list[str] | None = None,
    image_path: str | None = None,
    tool_calls: list[dict] | None = None,
    attachments: list[dict] | None = None,
):
    image_paths = image_paths or ([image_path] if image_path else None)
    if not content and not image_paths and not tool_calls and not attachments:
        return
    db = SessionLocal()
    try:
        s = _get_owned_session(db, session_id, user_id)
        if not s:
            s = ChatSession(session_uuid=session_id, user_id=user_id, title="")
            db.add(s)
            db.flush()
        db.add(ChatMessage(session_id=s.id, role=role, content=content, image_path=(image_paths or [None])[0], image_paths=image_paths, attachments=attachments, tool_calls=_sanitize_tool_calls(tool_calls)))
        s.message_count = (s.message_count or 0) + 1
        s.last_message_at = datetime.now()
        if role == "user" and (not s.title or s.title == ""):
            s.title = (content or "图片消息")[:50]
        db.commit()
    finally:
        db.close()


@router.post("/sessions/{session_id}/trash")
def trash_chat_session(
    session_id: str,
    expected_version: int | None = None,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.chat_service import chat_service
    session = chat_service.delete_session(db, session_id, current_user.id, expected_version=expected_version)
    return {"id": session_id, "message": "会话已移入回收站", "resource_version": session.resource_version, "purge_after": session.purge_after}
