"""
初始化种子数据
- 创建系统内置角色（admin/operator/viewer）与基础权限
- 创建默认管理员账号
- 创建本项目的检测场景（钢铁表面缺陷检测 / NEU-CLS）

执行方式（backend 目录下）：
    python -m app.database.seed
可重复执行：已存在的数据不会重复插入。
"""
from pathlib import Path
from app.config.settings import settings

from app.database.session import SessionLocal
from app.entity.db_models import (
    DetectionScene,
    ModelVersion,
    TrainingDataset,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
)
from app.core.security import hash_password

BUILTIN_DATASET_PATH = "NEU-DET.v9i.yolov11"

DEFAULT_PERMISSIONS = [
    ("detection:task:create", "创建检测任务", "detection"),
    ("detection:task:read", "查看检测任务", "detection"),
    ("detection:task:delete", "删除检测任务", "detection"),
    ("detection:task:read_all", "查看所有用户检测任务（不含私密正文）", "detection"),
    ("detection:task:delete_all", "管理所有用户检测任务回收站", "detection"),
    ("training:task:create", "创建训练任务", "training"),
    ("training:task:read", "查看训练任务", "training"),
    ("training:task:read_all", "查看所有用户训练任务", "training"),
    ("training:task:delete_all", "管理所有用户训练任务回收站", "training"),
    ("training:dataset:read_all", "查看所有用户数据集元数据", "training"),
    ("training:dataset:delete_all", "管理所有用户数据集回收站", "training"),
    ("model:manage", "管理模型版本", "training"),
    ("model:read_all", "查看所有用户模型元数据", "training"),
    ("model:manage_all", "管理所有用户模型", "training"),
    ("model:set_default", "切换系统默认模型", "training"),
    ("scene:manage", "管理检测场景", "detection"),
    ("agent:chat", "使用智能体对话", "agent"),
    ("knowledge:document:create", "上传知识文档", "knowledge"),
    ("knowledge:document:read", "查看/检索知识文档", "knowledge"),
    ("knowledge:document:delete", "删除知识文档", "knowledge"),
    ("knowledge:document:delete_all", "管理所有知识文档回收站（不含正文读取）", "knowledge"),
    ("knowledge:system:manage", "管理系统内置知识文档", "knowledge"),
    ("system:manage", "系统管理", "system"),
    ("system:user:read", "查看用户状态与资源元数据", "system"),
    ("system:user:status", "启用或禁用用户", "system"),
    ("system:user:delete", "删除用户与关联资源", "system"),
    ("system:audit:read", "读取脱敏审计日志", "system"),
    ("system:cleanup:read", "读取资源清理队列", "system"),
    ("system:cleanup:retry", "重试失败的资源清理任务", "system"),
]

DEFAULT_ROLES = {
    "admin": ("管理员", [code for code, _, _ in DEFAULT_PERMISSIONS]),
    "operator": (
        "操作员",
        [
            "detection:task:create", "detection:task:read",
            "training:task:create", "training:task:read",
            "agent:chat",
            "knowledge:document:create", "knowledge:document:read", "knowledge:document:delete",
        ],
    ),
    "viewer": ("访客", ["detection:task:read", "training:task:read", "knowledge:document:read"]),
}

# NEU-CLS 六类钢铁表面缺陷
NEU_CLS_CLASSES = ["crazing", "inclusion", "patches", "pitted", "rolled", "scratches"]
NEU_CLS_CLASSES_CN = {
    "crazing": "裂纹",
    "inclusion": "夹杂",
    "patches": "斑块",
    "pitted": "点蚀",
    "rolled": "氧化皮压入",
    "scratches": "划痕",
}


def seed_permissions(db) -> dict[str, Permission]:
    existing_codes = {p.code for p in db.query(Permission).all()}
    for code, name, module in DEFAULT_PERMISSIONS:
        if code not in existing_codes:
            db.add(Permission(code=code, name=name, module=module))
    db.commit()
    return {p.code: p for p in db.query(Permission).all()}


def seed_roles(db, permissions: dict[str, Permission]) -> dict[str, Role]:
    existing = {r.name: r for r in db.query(Role).all()}
    for name, (display_name, perm_codes) in DEFAULT_ROLES.items():
        role = existing.get(name)
        if not role:
            role = Role(name=name, display_name=display_name, is_system=True)
            db.add(role)
            db.flush()
            existing[name] = role

        current_codes = {rp.permission.code for rp in role.role_permissions}
        for code in perm_codes:
            if code not in current_codes and code in permissions:
                db.add(RolePermission(role_id=role.id, permission_id=permissions[code].id))
    db.commit()
    return {r.name: r for r in db.query(Role).all()}


def seed_admin_user(db, roles: dict[str, Role]) -> User:
    admin = db.query(User).filter(User.username == "admin").first()
    if not admin:
        password = settings.BOOTSTRAP_ADMIN_PASSWORD
        if len(password) < 12:
            raise ValueError("Set BOOTSTRAP_ADMIN_PASSWORD to a unique password of at least 12 characters before initial seeding")
        admin = User(
            username="admin",
            email=settings.BOOTSTRAP_ADMIN_EMAIL,
            hashed_password=hash_password(password),
            is_superuser=True,
        )
        db.add(admin)
        db.flush()
        print("[seed] Administrator created; credentials are supplied by deployment configuration")

    if "admin" in roles:
        has_role = (
            db.query(UserRole)
            .filter(UserRole.user_id == admin.id, UserRole.role_id == roles["admin"].id)
            .first()
        )
        if not has_role:
            db.add(UserRole(user_id=admin.id, role_id=roles["admin"].id))

    db.commit()
    return admin


def seed_detection_scenes(db, admin_user_id: int | None) -> None:
    existing = db.query(DetectionScene).filter(DetectionScene.name == "steel_surface_defect").first()
    if not existing:
        scene = DetectionScene(
            name="steel_surface_defect",
            display_name="钢铁表面缺陷检测",
            description="基于 NEU-CLS 数据集的钢铁表面缺陷检测场景",
            category="industry",
            class_names=NEU_CLS_CLASSES,
            class_names_cn=NEU_CLS_CLASSES_CN,
            created_by=admin_user_id,
        )
        db.add(scene)
        db.commit()
        print("[seed] 创建默认检测场景：steel_surface_defect（NEU-CLS 六类缺陷）")

    scene = existing or scene
    if scene.class_names != NEU_CLS_CLASSES or scene.class_names_cn != NEU_CLS_CLASSES_CN:
        scene.class_names = NEU_CLS_CLASSES
        scene.class_names_cn = NEU_CLS_CLASSES_CN
        db.commit()
        print("[seed] 同步检测场景类别字典到部署模型")
    model_path = "models/steel_surface_defect_v1.0.0/ssdd_yolo11n_v1.pt"
    absolute_model_path = Path(__file__).resolve().parents[3] / model_path
    if not absolute_model_path.is_file():
        print("[seed] No bundled model: install a trusted steel-defect checkpoint or upload one as an administrator")
        return
    model = (
        db.query(ModelVersion)
        .filter(ModelVersion.scene_id == scene.id, ModelVersion.version == "v1.0.0")
        .first()
    )
    if not model:
        model = ModelVersion(
            scene_id=scene.id,
            version="v1.0.0",
            model_name="ssdd_yolo11n_v1",
            model_type="yolo11n",
            model_path=model_path,
            file_size=absolute_model_path.stat().st_size if absolute_model_path.is_file() else None,
            is_default=True,
            is_builtin=True,
            description="钢铁表面缺陷检测首个部署权重",
        )
        db.add(model)
        db.commit()
        print("[seed] 注册默认模型：ssdd_yolo11n_v1（v1.0.0）")
    elif model.owner_id is None and not model.is_builtin:
        model.is_builtin = True
        db.commit()


def seed_builtin_datasets(db) -> None:
    """Register the one dataset shipped with the project as read-only."""
    if not (Path(settings.DATASET_BASE_DIR) / BUILTIN_DATASET_PATH).is_dir():
        return
    datasets = db.query(TrainingDataset).all()
    dataset = next((item for item in datasets if item.path == BUILTIN_DATASET_PATH), None)
    changed = False
    for item in datasets:
        should_be_builtin = item.path == BUILTIN_DATASET_PATH
        if item.is_builtin != should_be_builtin:
            item.is_builtin = should_be_builtin
            changed = True
        if should_be_builtin and item.owner_id is not None:
            item.owner_id = None
            changed = True
    if dataset is None:
        db.add(TrainingDataset(
            path=BUILTIN_DATASET_PATH,
            owner_id=None,
            is_builtin=True,
            display_name="NEU-DET.v9i.yolov11",
        ))
        changed = True
    if changed:
        db.commit()


def run_seed() -> None:
    db = SessionLocal()
    try:
        permissions = seed_permissions(db)
        roles = seed_roles(db, permissions)
        admin = seed_admin_user(db, roles)
        seed_detection_scenes(db, admin.id)
        seed_builtin_datasets(db)
        print("[seed] 种子数据初始化完成")
    finally:
        db.close()


if __name__ == "__main__":
    run_seed()
