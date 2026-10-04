"""
操作日志服务层
用于把关键操作（登录、密码修改、用户/模型删除、模型默认切换、批量清理等）
持久化到 operation_logs 表，作为审计留痕。

与 core/logger.py 的区别：
- core/logger.py 是写文件/终端的诊断日志（面向开发排错，不进数据库）
- 这里是写数据库的审计日志（面向运营复盘，管理端有专门页面查看）

调用惯例：
    from app.services.operation_log_service import operation_log_service
    operation_log_service.record(
        db, user=current_user, module="auth", action="login",
        target_type="user", target_id=str(current_user.id),
        description="用户登录成功",
        request=request,   # FastAPI Request 对象，可选，用于抓 IP / UA
    )

设计要点：
- 日志写入放在 try/except 里吞掉异常，永远不影响主业务流程
- username 字段冗余存储，即使用户被删除、user_id 被置 NULL，日志仍可读
- 支持不带 db.commit 的场景（调用方自己控制事务）
"""
from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.privacy import redact_text, redact_value
from app.entity.db_models import OperationLog, User

logger = get_logger(__name__)


def _redact_log_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return redact_text(value)


class OperationLogService:
    """操作审计日志服务"""

    @staticmethod
    def record(
        db: Session,
        *,
        user: Optional[User] = None,
        module: str,
        action: str,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        description: Optional[str] = None,
        status: str = "success",
        error_message: Optional[str] = None,
        request: Optional[Request] = None,
        request_id: Optional[str] = None,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
        commit: bool = True,
    ) -> Optional[OperationLog]:
        """
        写入一条操作日志。

        Args:
            db: 数据库 Session
            user: 当前操作用户；系统级操作可传 None
            module: 所属模块，如 auth/detection/training/agent/system
            action: 操作类型，如 create/update/delete/login/logout/export
            target_type: 操作对象类型，如 user/task/model/session
            target_id: 操作对象 ID（用字符串以兼容不同类型的主键）
            description: 人类可读的操作描述
            status: success / failure
            error_message: 失败时的错误信息
            request: FastAPI Request 对象；传入后自动抓取 IP、UA、方法、路径
            commit: 是否立即提交；默认 True，如果调用方希望把日志和业务操作放在
                    一个事务里，可以传 False，由调用方统一提交

        Returns:
            写入成功返回 OperationLog 实例，写入失败返回 None（不抛异常）

        写入日志失败不应影响主业务，因此这里吞掉所有异常，只在 logger 里留痕。
        """
        try:
            log = OperationLog(
                # Keep audit recording tolerant of lightweight user objects
                # used by background jobs and compatibility integrations.
                user_id=getattr(user, "id", None) if user else None,
                username=getattr(user, "username", None) if user else None,
                module=module,
                action=action,
                target_type=target_type,
                target_id=target_id,
                description=_redact_log_text(description),
                status=status,
                error_message=redact_value(error_message),
                request_id=request_id or getattr(getattr(request, "state", None), "request_id", None),
                task_id=task_id,
                session_id=session_id,
            )

            if request is not None:
                client_host = request.client.host if request.client else None
                log.ip_address = client_host
                log.user_agent = request.headers.get("user-agent")
                log.request_method = request.method
                log.request_path = request.url.path

            db.add(log)
            if commit:
                db.commit()
                db.refresh(log)
            else:
                db.flush()

            return log
        except Exception as exc:
            # 日志本身失败不能影响主业务；这里只在开发日志里留痕，不再上抛
            logger.warning("写入操作日志失败: %s", exc)
            try:
                db.rollback() if commit else None
            except Exception:
                pass
            return None

    @staticmethod
    def list_logs(
        db: Session,
        *,
        user_id: Optional[int] = None,
        module: Optional[str] = None,
        action: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[OperationLog], int]:
        """分页查询操作日志，支持按用户/模块/动作/状态筛选"""
        query = db.query(OperationLog)
        if user_id is not None:
            query = query.filter(OperationLog.user_id == user_id)
        if module:
            query = query.filter(OperationLog.module == module)
        if action:
            query = query.filter(OperationLog.action == action)
        if status:
            query = query.filter(OperationLog.status == status)

        total = query.count()
        items = (
            query.order_by(OperationLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total


# 全局单例
operation_log_service = OperationLogService()
