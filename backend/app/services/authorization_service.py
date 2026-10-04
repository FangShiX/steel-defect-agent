"""Central RBAC and resource-scope authorization helpers.

Permission codes are the normal authorization mechanism. ``is_superuser`` is
kept only as a break-glass compatibility fallback for legacy administrators
that have not yet been assigned the seeded ``admin`` role.
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.entity.db_models import Permission, RolePermission, User, UserRole


class AuthorizationService:
    @staticmethod
    def permission_codes(db: Session, user: User) -> set[str]:
        rows = (
            db.query(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .filter(UserRole.user_id == user.id)
            .all()
        )
        return {code for (code,) in rows}

    @staticmethod
    def has_permission(db: Session, user: User, code: str) -> bool:
        codes = AuthorizationService.permission_codes(db, user)
        if code in codes or "system:manage" in codes:
            return True
        # Transitional break-glass path for an old superuser row without RBAC.
        return bool(user.is_superuser and not codes)

    @staticmethod
    def require_permission(db: Session, user: User, code: str) -> None:
        if not AuthorizationService.has_permission(db, user, code):
            raise HTTPException(status_code=403, detail={
                "code": "permission_denied",
                "required_permission": code,
            })

    @staticmethod
    def can_access_owner(
        db: Session,
        user: User,
        owner_id: int | None,
        *,
        is_builtin: bool = False,
        cross_user_permission: str | None = None,
    ) -> bool:
        if is_builtin or owner_id == user.id:
            return True
        return bool(
            cross_user_permission
            and AuthorizationService.has_permission(db, user, cross_user_permission)
        )

    @staticmethod
    def require_owner(
        db: Session,
        user: User,
        owner_id: int | None,
        *,
        is_builtin: bool = False,
        cross_user_permission: str | None = None,
    ) -> None:
        if not AuthorizationService.can_access_owner(
            db,
            user,
            owner_id,
            is_builtin=is_builtin,
            cross_user_permission=cross_user_permission,
        ):
            raise HTTPException(status_code=403, detail={
                "code": "resource_forbidden",
                "message": "无权访问该资源",
            })


authorization_service = AuthorizationService()
