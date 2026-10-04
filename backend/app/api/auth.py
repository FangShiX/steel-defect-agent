"""
认证相关 API 路由
- POST /api/auth/register  用户注册
- POST /api/auth/login     用户登录
- GET  /api/auth/me        获取当前用户信息
"""

from datetime import datetime
from uuid import uuid4
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.security import create_access_token, decode_access_token
from app.core.logger import get_logger
from app.config.settings import settings
from app.database.session import get_db
from app.entity.db_models import (
    AuthSession, ChatSession, DetectionResult, DetectionTask, KnowledgeDocument, ModelVersion,
    TrainingDataset, TrainingTask, User,
)
from app.entity.schemas import (
    TokenResponse,
    UserLogin,
    UserRegister,
    UserResponse,
    UserUpdate,
    ChangePassword,
    PasswordResetRequest,
    PasswordResetConfirm,
    AdminPasswordReset,
)
from app.services.operation_log_service import operation_log_service
from app.services.action_confirmation_service import action_confirmation_service
from app.services.authorization_service import authorization_service
from app.services.user_service import user_service

router = APIRouter(prefix="/api/auth", tags=["认证"])

# OAuth2 密码模式，用于从请求 Header 中提取 Token
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
logger = get_logger(__name__)


async def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    """
    从 JWT Token 中解析当前用户
    在需要认证的路由中通过 Depends(get_current_user) 使用
    """
    credentials_exception = HTTPException(
        status_code=401,
        detail="无效的认证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        if payload.get("type") not in (None, "access"):
            raise credentials_exception
        user_id_str: Optional[str] = payload.get("sub")
        token_jti = payload.get("jti")
        if user_id_str is None:
            raise credentials_exception
        user_id = int(user_id_str)
    except (JWTError, ValueError):
        raise credentials_exception

    try:
        user = user_service.get_user_by_id(db, user_id)
    except HTTPException:
        # A signed token for a deleted user is still an invalid credential.
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(status_code=403, detail={"code": "ACCOUNT_DISABLED", "message": "账号已被禁用"})
    if token_jti:
        auth_session = db.query(AuthSession).filter(
            AuthSession.access_jti == token_jti,
            AuthSession.revoked_at.is_(None),
        ).first()
        if not auth_session:
            raise credentials_exception
        request.state.auth_session_id = auth_session.session_uuid
        request.state.auth_jti = token_jti
        now = datetime.now()
        if auth_session.last_seen_at is None or (now - auth_session.last_seen_at).total_seconds() >= 60:
            auth_session.last_seen_at = now
            db.commit()
    request.state.user_id = user.id
    return user


def _issue_session(db: Session, user: User, http_request: Request, existing: AuthSession | None = None) -> dict:
    access_token = create_access_token({"sub": str(user.id), "type": "access"})
    refresh_token = create_access_token({"sub": str(user.id), "type": "refresh"}, expires_minutes=60 * 24 * 7)
    access_claims = decode_access_token(access_token)
    refresh_claims = decode_access_token(refresh_token)
    now = datetime.now()
    session = existing or AuthSession(session_uuid=str(uuid4()), user_id=user.id)
    session.access_jti = access_claims["jti"]
    session.refresh_jti = refresh_claims["jti"]
    session.created_at = session.created_at or now
    session.last_seen_at = now
    session.access_expires_at = datetime.fromtimestamp(access_claims["exp"])
    session.refresh_expires_at = datetime.fromtimestamp(refresh_claims["exp"])
    session.revoked_at = None
    session.ip_address = http_request.client.host if http_request.client else None
    session.user_agent = http_request.headers.get("user-agent")
    if existing is None:
        db.add(session)
    db.commit()
    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer", "session_id": session.session_uuid}


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    http_request: Request,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    """Rotate a refresh token and invalidate the previous access token."""
    try:
        payload = decode_access_token(token)
        if payload.get("type") != "refresh":
            raise ValueError("not a refresh token")
        session = db.query(AuthSession).filter(
            AuthSession.refresh_jti == payload.get("jti"),
            AuthSession.revoked_at.is_(None),
        ).first()
        if not session or session.refresh_expires_at <= datetime.now():
            raise ValueError("expired or revoked session")
        user = user_service.get_user_by_id(db, int(payload["sub"]))
        if not user.is_active:
            raise HTTPException(status_code=403, detail={"code": "ACCOUNT_DISABLED", "message": "账号已被禁用"})
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail={"code": "REFRESH_TOKEN_INVALID", "message": "刷新令牌无效或已过期"})
    pair = _issue_session(db, user, http_request, existing=session)
    return {**pair, "user": {
        "id": user.id, "username": user.username, "email": user.email,
        "avatar": user.avatar, "roles": user_service.get_user_roles(db, user),
        "is_active": user.is_active, "is_superuser": user.is_superuser,
    }}


@router.post("/logout")
async def logout(
    http_request: Request,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    auth_session = db.query(AuthSession).filter(AuthSession.access_jti == http_request.state.auth_jti).first()
    if auth_session and auth_session.revoked_at is None:
        auth_session.revoked_at = datetime.now()
        db.commit()
    operation_log_service.record(db, user=current_user, module="auth", action="logout", target_type="session", target_id=getattr(http_request.state, "auth_session_id", None), request=http_request)
    return {"message": "已退出当前会话"}


@router.get("/sessions")
async def list_auth_sessions(
    http_request: Request,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sessions = db.query(AuthSession).filter(AuthSession.user_id == current_user.id).order_by(AuthSession.created_at.desc()).all()
    now = datetime.now()
    return [{
        "id": item.session_uuid,
        "created_at": item.created_at,
        "last_seen_at": item.last_seen_at,
        "expires_at": item.refresh_expires_at,
        "revoked": item.revoked_at is not None,
        "current": item.session_uuid == getattr(http_request.state, "auth_session_id", None),
        "active": item.revoked_at is None and item.refresh_expires_at > now,
        "ip_address": item.ip_address,
        "user_agent": item.user_agent,
    } for item in sessions]


@router.delete("/sessions/{session_uuid}")
async def revoke_auth_session(
    session_uuid: str,
    http_request: Request,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = db.query(AuthSession).filter(AuthSession.session_uuid == session_uuid, AuthSession.user_id == current_user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail={"code": "SESSION_NOT_FOUND", "message": "登录会话不存在"})
    session.revoked_at = session.revoked_at or datetime.now()
    db.commit()
    operation_log_service.record(db, user=current_user, module="auth", action="revoke_session", target_type="session", target_id=session_uuid, request=http_request)
    return {"id": session_uuid, "message": "会话已失效"}


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    request: UserRegister, http_request: Request, db: Session = Depends(get_db)
):
    """
    用户注册

    - **username**: 用户名（3-50 字符）
    - **email**: 邮箱
    - **password**: 密码（至少 6 位）
    """
    user = user_service.register(
        db=db,
        username=request.username,
        email=request.email,
        password=request.password,
    )
    operation_log_service.record(
        db,
        user=user,
        module="auth",
        action="register",
        target_type="user",
        target_id=str(user.id),
        description=f"用户注册：{user.username}",
        request=http_request,
    )
    return user


@router.post("/login", response_model=TokenResponse)
async def login(http_request: Request, db: Session = Depends(get_db)):
    """
    用户登录

    - 返回 JWT access_token
    - 后续请求在 Header 中携带：Authorization: Bearer <token>

    同时支持 JSON 请求体（前端使用）和 form-urlencoded（Swagger OAuth2 弹窗使用）。
    """
    content_type = http_request.headers.get("content-type", "")

    if "application/json" in content_type:
        payload = await http_request.json()
        username = payload.get("username")
        password = payload.get("password")
    else:
        # form-urlencoded：Swagger 的 OAuth2 弹窗和标准 OAuth2 客户端走这条路径
        form = await http_request.form()
        username = form.get("username")
        password = form.get("password")

    if not username or not password:
        raise HTTPException(status_code=422, detail="用户名和密码不能为空")

    try:
        user = user_service.login(db=db, username=username, password=password)
    except HTTPException as exc:
        operation_log_service.record(
            db,
            user=None,
            module="auth",
            action="login",
            target_type="user",
            target_id=str(username),
            description=f"登录失败：{username}",
            status="failure",
            error_message=str(exc.detail),
            request=http_request,
        )
        raise

    operation_log_service.record(
        db,
        user=user,
        module="auth",
        action="login",
        target_type="user",
        target_id=str(user.id),
        description=f"用户登录：{user.username}",
        request=http_request,
    )
    token_pair = _issue_session(db, user, http_request)
    roles = user_service.get_user_roles(db, user)

    return {
        **token_pair,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "avatar": user.avatar,
            "roles": roles,
            "is_active": user.is_active,
            "is_superuser": user.is_superuser,
            "phone": user.phone,
            "avatar": user.avatar,
            "is_superuser": user.is_superuser,
        },
    }


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取当前登录用户信息（需要 Token 认证）"""
    roles = user_service.get_user_roles(db, current_user)
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "phone": current_user.phone,
        "avatar": current_user.avatar,
        "is_active": current_user.is_active,
        "is_superuser": current_user.is_superuser,
        "roles": roles,
        "last_login_at": current_user.last_login_at,
        "created_at": current_user.created_at,
    }


@router.put("/me", response_model=UserResponse)
async def update_profile(
    payload: UserUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新当前用户资料（username/phone/avatar/email，均可选）"""
    user = user_service.update_profile(
        db,
        current_user,
        payload.phone,
        payload.avatar,
        payload.email,
        payload.username,
    )
    roles = user_service.get_user_roles(db, user)
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "phone": user.phone,
        "avatar": user.avatar,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
        "roles": roles,
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
    }


@router.post("/change-password")
async def change_password(
    payload: ChangePassword,
    http_request: Request,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """已登录状态下修改密码，需提供旧密码校验"""
    user_service.change_password(
        db, current_user, payload.old_password, payload.new_password,
        current_session_uuid=getattr(http_request.state, "auth_session_id", None),
    )
    operation_log_service.record(
        db,
        user=current_user,
        module="auth",
        action="change_password",
        target_type="user",
        target_id=str(current_user.id),
        description="修改密码",
        request=http_request,
    )
    return {"message": "密码修改成功"}


@router.post("/password-reset/request")
async def request_password_reset(
    payload: PasswordResetRequest, db: Session = Depends(get_db)
):
    """
    忘记密码：申请重置令牌。
    出于安全考虑，无论邮箱是否存在都返回相同提示；实际发送重置邮件的逻辑（含 raw_token）
    由负责邮件发送的同学接入，这里只负责生成并落库令牌。
    """
    if not settings.SMTP_HOST or not settings.SMTP_FROM_EMAIL:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "PASSWORD_RESET_DELIVERY_UNAVAILABLE",
                "message": "Password reset email delivery is not configured",
            },
        )
    raw_token = user_service.request_password_reset(db, payload.email)
    if raw_token:
        try:
            user_service.send_password_reset_email(payload.email, raw_token)
        except Exception as exc:
            logger.error("Password reset email delivery failed: %s", exc, exc_info=True)
    return {"message": "如果该邮箱已注册，重置链接将发送到您的邮箱"}


@router.post("/password-reset/confirm")
async def confirm_password_reset(
    payload: PasswordResetConfirm, db: Session = Depends(get_db)
):
    """忘记密码：使用邮件中的令牌设置新密码"""
    user_service.confirm_password_reset(db, payload.token, payload.new_password)
    return {"message": "密码重置成功，请使用新密码登录"}


@router.get("/users")
async def list_users_for_admin(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return admin-safe user and resource metadata without private content."""
    authorization_service.require_permission(db, current_user, "system:user:read")
    query = db.query(User)
    total = query.count()
    users = (
        query.order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = []
    for user in users:
        items.append({
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_active": user.is_active,
            "is_superuser": user.is_superuser,
            "phone": user.phone,
            "avatar": user.avatar,
            "roles": user_service.get_user_roles(db, user),
            "last_login_at": user.last_login_at,
            "created_at": user.created_at,
            "resource_counts": {
                "detection_tasks": db.query(DetectionTask).filter(DetectionTask.user_id == user.id).count(),
                "training_tasks": db.query(TrainingTask).filter(TrainingTask.user_id == user.id).count(),
                "datasets": db.query(TrainingDataset).filter(TrainingDataset.owner_id == user.id).count(),
                "models": db.query(ModelVersion).filter(ModelVersion.owner_id == user.id).count(),
                "knowledge_documents": db.query(KnowledgeDocument).filter(KnowledgeDocument.user_id == user.id).count(),
            },
        })
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "items": items,
    }


@router.post("/users/{user_id}/password-reset")
async def admin_reset_password(
    user_id: int,
    payload: AdminPasswordReset,
    http_request: Request,
    confirmation_id: str | None = Header(default=None, alias="X-Confirmation-ID"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "admin permission required"})
    action_confirmation_service.require_or_prepare(
        db, confirmation_uuid=confirmation_id, user_id=current_user.id,
        operation="admin_reset_password", target_type="user", target_id=str(user_id),
        impact={"scope": "replace password and revoke all active sessions", "reversible": False},
        payload={"user_id": user_id}, request_id=getattr(http_request.state, "request_id", None),
    )
    user_service.admin_reset_password(db, user_id, payload.new_password)
    operation_log_service.record(
        db, user=current_user, module="auth", action="admin_reset_password",
        target_type="user", target_id=str(user_id), description="administrator reset password",
        request=http_request,
    )
    return {"message": "password reset and active sessions revoked"}


@router.get("/resource-status")
def get_resource_status(
    http_request: Request,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Administrator overview of owned resources, task state, and pending cleanup."""
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "需要管理员权限"})
    cleanup_pending = {
        "models": db.query(ModelVersion).filter(ModelVersion.cleanup_pending.is_(True)).count(),
        "detection_results": db.query(DetectionResult).filter(DetectionResult.cleanup_pending.is_(True)).count(),
        "knowledge_documents": db.query(KnowledgeDocument).filter(KnowledgeDocument.cleanup_pending.is_(True)).count(),
    }
    operation_log_service.record(
        db, user=current_user, module="system", action="view_resource_status",
        description="查看资源、任务与清理状态总览", request=http_request,
    )
    return {
        "resources": {
            "users": db.query(User).count(),
            "datasets": db.query(TrainingDataset).count(),
            "models": db.query(ModelVersion).count(),
            "knowledge_documents": db.query(KnowledgeDocument).count(),
            "sessions": db.query(ChatSession).count(),
        },
        "tasks": {
            "detection": {status: db.query(DetectionTask).filter(DetectionTask.status == status).count() for status in ("pending", "processing", "completed", "failed")},
            "training": {status: db.query(TrainingTask).filter(TrainingTask.status == status).count() for status in ("pending", "running", "completed", "failed", "cancelled")},
        },
        "cleanup_pending": cleanup_pending,
        "cleanup_pending_total": sum(cleanup_pending.values()),
    }


@router.post("/users/{user_id}/deactivate")
async def deactivate_user(
    user_id: int,
    http_request: Request,
    confirmation_id: str | None = Header(default=None, alias="X-Confirmation-ID"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """管理员禁用某个用户账号"""
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail={"code": "SELF_PROTECTION", "message": "不能禁用当前登录的管理员"})
    action_confirmation_service.require_or_prepare(
        db, confirmation_uuid=confirmation_id, user_id=current_user.id,
        operation="deactivate_user", target_type="user", target_id=str(user_id),
        impact={"scope": "disable account and revoke all its active sessions", "reversible": True},
        payload={"user_id": user_id}, request_id=getattr(http_request.state, "request_id", None),
    )
    authorization_service.require_permission(db, current_user, "system:user:status")
    user_service.set_active(db, user_id, is_active=False)
    db.query(AuthSession).filter(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)).update({"revoked_at": datetime.now()}, synchronize_session=False)
    db.commit()
    operation_log_service.record(
        db,
        user=current_user,
        module="system",
        action="deactivate_user",
        target_type="user",
        target_id=str(user_id),
        description=f"禁用用户 id={user_id}",
        request=http_request,
    )
    return {"message": "用户已禁用"}


@router.post("/users/{user_id}/activate")
async def activate_user(
    user_id: int,
    http_request: Request,
    confirmation_id: str | None = Header(default=None, alias="X-Confirmation-ID"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """管理员重新启用某个用户账号"""
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    action_confirmation_service.require_or_prepare(
        db, confirmation_uuid=confirmation_id, user_id=current_user.id,
        operation="activate_user", target_type="user", target_id=str(user_id),
        impact={"scope": "restore account access", "reversible": True},
        payload={"user_id": user_id}, request_id=getattr(http_request.state, "request_id", None),
    )
    authorization_service.require_permission(db, current_user, "system:user:status")
    user_service.set_active(db, user_id, is_active=True)
    operation_log_service.record(
        db,
        user=current_user,
        module="system",
        action="activate_user",
        target_type="user",
        target_id=str(user_id),
        description=f"启用用户 id={user_id}",
        request=http_request,
    )
    return {"message": "用户已启用"}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    http_request: Request,
    confirmation_id: str | None = Header(default=None, alias="X-Confirmation-ID"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """管理员删除用户，事务化级联清理其全部关联数据（对应任务文档步骤 13）"""
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail={"code": "SELF_PROTECTION", "message": "不能删除当前登录的管理员"})
    action_confirmation_service.require_or_prepare(
        db, confirmation_uuid=confirmation_id, user_id=current_user.id,
        operation="delete_user", target_type="user", target_id=str(user_id),
        impact={"scope": "user and all owned tasks, files, sessions, and logs ownership", "reversible": False},
        payload={"user_id": user_id}, request_id=getattr(http_request.state, "request_id", None),
    )
    # 先记录日志（此时 user 还没被删，target_id 才能引用到）
    operation_log_service.record(
        db,
        user=current_user,
        module="system",
        action="delete_user",
        target_type="user",
        target_id=str(user_id),
        description=f"删除用户 id={user_id} 及其关联数据",
        request=http_request,
    )
    return {"message": "用户及其关联数据已删除"}
