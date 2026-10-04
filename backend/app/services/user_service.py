"""
用户服务层
处理用户注册、登录、鉴权、资料与密码管理，以及删除用户的级联清理
"""
import hashlib
import secrets
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from urllib.parse import quote
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.entity.db_models import (
    AuthSession,
    User, DetectionTask, TrainingTask,
    ModelVersion, ChatSession, KnowledgeDocument, DetectionScene, OperationLog,
    PasswordResetToken, TrainingDataset, ResourceCleanupJob, StoredFile,
)
from app.config.settings import settings
from app.storage.minio_client import MinIOClient

RESET_TOKEN_TTL_MINUTES = 60


class UserService:
    """用户服务"""

    # ── 注册 / 登录 ──────────────────────────────────────

    @staticmethod
    def register(db: Session, username: str, email: str, password: str) -> User:
        """
        用户注册

        Raises:
            HTTPException: 用户名或邮箱已存在
        """
        if db.query(User).filter(User.username == username).first():
            raise HTTPException(status_code=400, detail="用户名已存在")
        if db.query(User).filter(User.email == email).first():
            raise HTTPException(status_code=400, detail="邮箱已被注册")

        new_user = User(
            username=username,
            email=email,
            hashed_password=hash_password(password),
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        return new_user

    @staticmethod
    def login(db: Session, username: str, password: str) -> User:
        """
        用户登录

        Raises:
            HTTPException: 用户名或密码错误、账号已被禁用
        """
        user = db.query(User).filter(User.username == username).first()
        if not user or not verify_password(password, user.hashed_password):
            raise HTTPException(status_code=401, detail="用户名或密码错误")

        if not user.is_active:
            raise HTTPException(status_code=403, detail="账号已被禁用，请联系管理员")

        user.last_login_at = datetime.now()
        db.commit()
        return user

    @staticmethod
    def create_access_token_for_user(user: User) -> str:
        """为用户生成 JWT Token"""
        return create_access_token(data={"sub": str(user.id)})

    @staticmethod
    def get_user_roles(db: Session, user: User) -> list[str]:
        """获取用户的角色标识列表"""
        return [ur.role.name for ur in user.user_roles]

    @staticmethod
    def get_user_by_id(db: Session, user_id: int) -> User:
        """根据 ID 获取用户"""
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        return user

    @staticmethod
    def list_users(db: Session, page: int = 1, page_size: int = 20) -> tuple[list[User], int]:
        query = db.query(User)
        total = query.count()
        users = (
            query.order_by(User.created_at.desc(), User.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return users, total

    # ── 资料 / 密码管理 ──────────────────────────────────

    @staticmethod
    def update_profile(
        db: Session,
        user: User,
        phone: str | None,
        avatar: str | None,
        email: str | None,
        username: str | None = None,
    ) -> User:
        """更新用户资料（username/phone/avatar/email，均可选）"""
        if username is not None:
            username = username.strip()
            if not username:
                raise HTTPException(status_code=400, detail="用户名不能为空")
            if username != user.username:
                if db.query(User).filter(User.username == username, User.id != user.id).first():
                    raise HTTPException(status_code=400, detail="用户名已存在")
                user.username = username
        if email and email != user.email:
            if db.query(User).filter(User.email == email, User.id != user.id).first():
                raise HTTPException(status_code=400, detail="邮箱已被其他账号使用")
            user.email = email
        if phone is not None:
            user.phone = phone
        if avatar is not None:
            user.avatar = avatar
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def change_password(
        db: Session,
        user: User,
        old_password: str,
        new_password: str,
        current_session_uuid: str | None = None,
    ) -> None:
        """已登录状态下修改密码，需校验旧密码"""
        if not verify_password(old_password, user.hashed_password):
            raise HTTPException(status_code=400, detail="旧密码不正确")
        user.hashed_password = hash_password(new_password)
        sessions = db.query(AuthSession).filter(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
        )
        if current_session_uuid:
            sessions = sessions.filter(AuthSession.session_uuid != current_session_uuid)
        sessions.update({"revoked_at": datetime.now()}, synchronize_session=False)
        db.commit()

    @staticmethod
    def set_active(db: Session, user_id: int, is_active: bool) -> User:
        """管理员启用/禁用用户"""
        user = UserService.get_user_by_id(db, user_id)
        user.is_active = is_active
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def admin_reset_password(db: Session, user_id: int, new_password: str) -> User:
        user = UserService.get_user_by_id(db, user_id)
        user.hashed_password = hash_password(new_password)
        db.query(AuthSession).filter(
            AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
        ).update({"revoked_at": datetime.now()}, synchronize_session=False)
        db.commit()
        db.refresh(user)
        return user

    # ── 忘记密码（邮箱 + 令牌） ───────────────────────────

    @staticmethod
    def request_password_reset(db: Session, email: str) -> str | None:
        """
        生成密码重置令牌。
        为避免暴露"邮箱是否存在"，邮箱不存在时也返回 None 而不是报错，
        路由层统一返回"如果邮箱存在，重置邮件已发送"这类模糊提示。

        Returns:
            重置令牌明文（用于发邮件），邮箱不存在时返回 None
        """
        user = db.query(User).filter(User.email == email).first()
        if not user:
            return None

        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        db.add(PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.now() + timedelta(minutes=RESET_TOKEN_TTL_MINUTES),
        ))
        db.commit()
        return raw_token

    @staticmethod
    def send_password_reset_email(email: str, raw_token: str) -> None:
        if not settings.SMTP_HOST or not settings.SMTP_FROM_EMAIL:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "PASSWORD_RESET_DELIVERY_UNAVAILABLE",
                    "message": "Password reset email delivery is not configured",
                },
            )
        reset_url = f"{settings.PASSWORD_RESET_URL}?token={quote(raw_token)}"
        message = EmailMessage()
        message["Subject"] = "Password reset"
        message["From"] = settings.SMTP_FROM_EMAIL
        message["To"] = email
        message.set_content(
            "Use the following link within 60 minutes to reset your password:\n\n"
            f"{reset_url}\n\nIf you did not request this, ignore this email."
        )
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as client:
            if settings.SMTP_USE_TLS:
                client.starttls()
            if settings.SMTP_USERNAME:
                client.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            client.send_message(message)

    @staticmethod
    def confirm_password_reset(db: Session, raw_token: str, new_password: str) -> None:
        """校验重置令牌并设置新密码"""
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        token = (
            db.query(PasswordResetToken)
            .filter(PasswordResetToken.token_hash == token_hash, PasswordResetToken.used.is_(False))
            .first()
        )
        if not token or token.expires_at < datetime.now():
            raise HTTPException(status_code=400, detail="重置链接无效或已过期")

        user = db.query(User).filter(User.id == token.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        user.hashed_password = hash_password(new_password)
        token.used = True
        db.query(AuthSession).filter(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
        ).update({"revoked_at": datetime.now()}, synchronize_session=False)
        db.commit()

    # ── 删除用户（事务 + 级联清理） ───────────────────────

    @staticmethod
    def delete_user_cascade(
        db: Session,
        user_id: int,
        cleanup_job_id: int | None = None,
    ) -> ResourceCleanupJob:
        """
        管理员删除用户的完整级联清理，对应任务文档第 13 步：
        同一事务内先清理子表和 MinIO 文件，再删除主记录，任一步失败整体回滚。

        DetectionResult / TrainingMetric / ChatMessage / password_reset_tokens
        通过 ORM relationship 的 cascade="all, delete-orphan"（或 DB 级 ON DELETE CASCADE）
        自动跟随父记录一起删除，这里不需要手动处理。
        """
        minio = None
        job_id = cleanup_job_id

        def delete_object_url(value: str | None) -> None:
            nonlocal minio
            if not value:
                return
            if minio is None:
                minio = MinIOClient()
            minio.delete_by_url(value, suppress_errors=False)

        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                if cleanup_job_id is not None:
                    job = db.query(ResourceCleanupJob).filter(
                        ResourceCleanupJob.id == cleanup_job_id
                    ).first()
                    if job:
                        job.status = "completed"
                        job.error_message = None
                        job.completed_at = datetime.now()
                        db.commit()
                        return job
                raise HTTPException(status_code=404, detail="用户不存在")

            tasks = db.query(DetectionTask).filter(DetectionTask.user_id == user_id).all()
            sessions = db.query(ChatSession).filter(ChatSession.user_id == user_id).all()
            docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.user_id == user_id).all()
            models = db.query(ModelVersion).filter(ModelVersion.owner_id == user_id).all()
            object_urls = sorted({
                value
                for value in (
                    [
                        item
                        for task in tasks
                        for result in task.results
                        for item in (result.image_path, result.annotated_image_url)
                    ]
                    + [
                        item
                        for session in sessions
                        for message in session.messages
                        for item in ([message.image_path] + list(message.image_paths or []))
                    ]
                    + [document.file_url for document in docs]
                    + [model.minio_url for model in models]
                )
                if value
            })

            if cleanup_job_id is None:
                job = ResourceCleanupJob(
                    resource_type="user",
                    resource_id=str(user_id),
                    owner_id=user_id,
                    action="cascade_delete",
                    status="running",
                    object_keys=object_urls,
                )
                db.add(job)
                db.commit()
                db.refresh(job)
                job_id = job.id
            else:
                job = db.query(ResourceCleanupJob).filter(
                    ResourceCleanupJob.id == cleanup_job_id,
                    ResourceCleanupJob.resource_type == "user",
                    ResourceCleanupJob.resource_id == str(user_id),
                ).first()
                if not job:
                    raise HTTPException(status_code=404, detail="清理任务不存在")
                job.status = "running"
                job.error_message = None
                job.completed_at = None
                job.object_keys = object_urls
                db.commit()

            # 1. 检测任务：先清理每张结果图的 MinIO 文件，再删任务（级联删 detection_results）
            for task in tasks:
                for result in task.results:
                    delete_object_url(result.image_path)
                    delete_object_url(result.annotated_image_url)
                db.delete(task)

            # 2. 训练任务：产出的模型版本（ModelVersion）要保留，只解除关联，再删任务（级联删 training_metrics）
            training_tasks = db.query(TrainingTask).filter(TrainingTask.user_id == user_id).all()
            training_task_ids = [t.id for t in training_tasks]
            if training_task_ids:
                db.query(ModelVersion).filter(
                    ModelVersion.training_task_id.in_(training_task_ids)
                ).update({ModelVersion.training_task_id: None}, synchronize_session=False)
            for t in training_tasks:
                db.delete(t)

            # 3. 对话会话：删除会话（级联删 chat_messages）
            for s in sessions:
                for message in s.messages:
                    for value in ([message.image_path] + list(message.image_paths or []) + [item.get("path") for item in (message.attachments or [])]):
                        if not value:
                            continue
                        if value.startswith(("http://", "https://")):
                            delete_object_url(value)
                            continue
                        upload_root = (Path(tempfile.gettempdir()) / "rsod_uploads").resolve()
                        attachment = Path(value).resolve()
                        if upload_root not in attachment.parents:
                            raise ValueError("聊天附件不在受控上传目录中")
                        if attachment.is_file():
                            attachment.unlink()
                db.delete(s)

            # 4. 知识文档：清理 MinIO 原文件，删除文档（级联删 knowledge_chunks）
            for d in docs:
                if d.object_key:
                    if minio is None:
                        minio = MinIOClient()
                    minio.delete_file(d.object_key)
                else:
                    delete_object_url(d.file_url)
                db.delete(d)

            # The local file ledger is part of the same owned-resource cascade.
            for record in db.query(StoredFile).filter(StoredFile.user_id == user_id).all():
                if record.status != "deleted":
                    if minio is None:
                        minio = MinIOClient()
                    minio.delete_file(record.object_key)
                db.delete(record)

            # 5. 用户数据集：物理目录使用 storage_key，与显示名称分离。
            project_root = Path(__file__).resolve().parents[3]
            dataset_root = (project_root / settings.DATASET_BASE_DIR).resolve()
            datasets = db.query(TrainingDataset).filter(TrainingDataset.owner_id == user_id).all()
            for dataset in datasets:
                for base in (dataset_root, dataset_root / ".trash"):
                    target = (base / dataset.storage_key).resolve()
                    if base.resolve() not in target.parents:
                        raise ValueError("数据集目录不在受控存储范围内")
                    if target.is_dir():
                        shutil.rmtree(target)
                db.delete(dataset)

            # 6. 私有模型资产：清理对象存储和受控 models 目录中的本地文件。
            models_root = (project_root / "models").resolve()
            for model in models:
                delete_object_url(model.minio_url)
                model_path = (project_root / model.model_path).resolve()
                if model_path.is_file() and models_root not in model_path.parents:
                    raise ValueError("模型文件不在受控 models 目录中")
                if model_path.is_file():
                    model_path.unlink()
                db.delete(model)

            # 7. 该用户创建的检测场景：保留场景，只解除创建者关联
            db.query(DetectionScene).filter(DetectionScene.created_by == user_id).update(
                {DetectionScene.created_by: None}, synchronize_session=False
            )

            # 8. 操作日志/清理任务：保留审计信息，只解除用户关联
            db.query(OperationLog).filter(OperationLog.user_id == user_id).update(
                {OperationLog.user_id: None}, synchronize_session=False
            )
            db.query(ResourceCleanupJob).filter(ResourceCleanupJob.owner_id == user_id).update(
                {ResourceCleanupJob.owner_id: None}, synchronize_session=False
            )

            # 9. user_roles 由 User.user_roles 的 cascade="all, delete-orphan" 自动清理
            # 10. password_reset_tokens 由数据库 ON DELETE CASCADE 自动清理

            # 11. 最后删除用户本身
            db.delete(user)
            job.owner_id = None
            job.status = "completed"
            job.error_message = None
            job.completed_at = datetime.now()
            db.commit()
            db.refresh(job)
            return job
        except HTTPException:
            db.rollback()
            raise
        except Exception as exc:
            db.rollback()
            if job_id is not None:
                failed_job = db.query(ResourceCleanupJob).filter(
                    ResourceCleanupJob.id == job_id
                ).first()
                if failed_job:
                    failed_job.status = "failed"
                    failed_job.retry_count += 1
                    failed_job.error_message = str(exc)
                    db.commit()
            raise HTTPException(status_code=502, detail={
                "code": "storage_cleanup_failed",
                "cleanup_job_id": job_id,
                "message": "用户资源清理失败，已保留可重试任务",
            }) from exc


# 全局单例
user_service = UserService()
