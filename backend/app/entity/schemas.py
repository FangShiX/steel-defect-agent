"""
Pydantic 请求/响应模型
用于 API 接口的数据验证和序列化

分层原则：
  - Create 模型：创建资源时的请求体
  - Update 模型：更新资源时的请求体（所有字段可选）
  - Response 模型：API 返回的响应体（过滤敏感字段）
  - List 模型：分页列表查询的参数和响应
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ══════════════════════════════════════════════════════════════
# 一、用户与权限
# ══════════════════════════════════════════════════════════════

# --- 认证相关 ---

class UserRegister(BaseModel):
    """用户注册请求"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    email: str = Field(..., description="邮箱")
    password: str = Field(..., min_length=6, max_length=100, description="密码")


class UserLogin(BaseModel):
    """用户登录请求"""
    username: str = Field(..., description="用户名或邮箱")
    password: str = Field(..., description="密码")


class UserBrief(BaseModel):
    """用户简要信息（嵌入在 Token 响应中）"""
    id: int
    username: str
    email: str
    avatar: Optional[str] = None
    roles: list[str] = []
    is_active: bool = True
    is_superuser: bool = False

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    """登录成功响应"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserBrief


# --- 用户管理 ---

class UserResponse(BaseModel):
    """用户详情响应"""
    id: int
    username: str
    email: str
    phone: Optional[str] = None
    avatar: Optional[str] = None
    is_active: bool
    is_superuser: bool
    roles: list[str] = []
    last_login_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserUpdate(BaseModel):
    """用户信息更新"""
    username: Optional[str] = None
    phone: Optional[str] = None
    avatar: Optional[str] = None
    email: Optional[str] = None


class StoredFileResponse(BaseModel):
    """文件台账响应，不暴露 MinIO 密钥，仅返回短期访问地址。"""
    id: int
    user_id: int
    object_key: str
    original_filename: str
    content_type: Optional[str] = None
    file_size: int
    checksum: Optional[str] = None
    resource_type: str
    resource_id: Optional[str] = None
    status: str
    cleanup_error: Optional[str] = None
    download_url: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ChangePassword(BaseModel):
    """修改密码"""
    old_password: str = Field(..., description="旧密码")
    new_password: str = Field(..., min_length=6, max_length=100, description="新密码")


class PasswordResetRequest(BaseModel):
    """忘记密码：申请重置令牌"""
    email: str = Field(..., description="注册邮箱")


class PasswordResetConfirm(BaseModel):
    """忘记密码：使用令牌设置新密码"""
    token: str = Field(..., description="重置令牌明文")
    new_password: str = Field(..., min_length=6, max_length=100, description="新密码")


# --- 角色权限 ---

class AdminPasswordReset(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=100)


class RoleResponse(BaseModel):
    """角色响应"""
    id: int
    name: str
    display_name: str
    description: Optional[str] = None
    is_system: bool
    permissions: list[str] = []  # 权限编码列表
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RoleCreate(BaseModel):
    """创建角色"""
    name: str = Field(..., min_length=2, max_length=50, description="角色标识")
    display_name: str = Field(..., description="角色显示名")
    description: Optional[str] = None
    permission_codes: list[str] = Field(default=[], description="权限编码列表")


class PermissionResponse(BaseModel):
    """权限响应"""
    id: int
    code: str
    name: str
    module: str
    description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ══════════════════════════════════════════════════════════════
# 二、检测业务
# ══════════════════════════════════════════════════════════════

# --- 检测场景 ---

class SceneCreate(BaseModel):
    """创建检测场景"""
    name: str = Field(..., description="场景标识，如 remote_sensing")
    display_name: str = Field(..., description="场景显示名，如 遥感目标检测")
    description: Optional[str] = None
    category: str = Field(..., description="分类：agriculture/industry/remote_sensing/medical/traffic")
    class_names: list[str] = Field(..., description="类别列表")
    class_names_cn: Optional[dict[str, str]] = Field(None, description="中文名映射")


class SceneResponse(BaseModel):
    """检测场景响应"""
    id: int
    name: str
    display_name: str
    description: Optional[str] = None
    category: str
    class_names: list
    class_names_cn: Optional[dict] = None
    is_active: bool
    default_model: Optional["ModelVersionBrief"] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- 检测任务 ---

class DetectionTaskResponse(BaseModel):
    """检测任务响应"""
    id: int
    public_task_id: str
    user_id: int
    scene_id: int
    scene_name: Optional[str] = None
    model_version_id: Optional[int] = None
    task_type: str
    status: str
    total_images: int
    total_objects: int
    total_inference_time: float
    conf_threshold: float
    iou_threshold: float
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    resource_version: int = 1
    deletion_status: str = "active"

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())


class DetectionResultResponse(BaseModel):
    """单条检测结果响应"""
    id: int
    task_id: int
    image_path: str
    annotated_image_url: Optional[str] = None
    class_name: str
    class_name_cn: Optional[str] = None
    class_id: int
    confidence: float
    bbox: list  # [x1, y1, x2, y2]
    inference_time: Optional[float] = None
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DetectionTaskDetail(BaseModel):
    """检测任务详情（含结果列表）"""
    task: DetectionTaskResponse
    results: list[DetectionResultResponse] = Field(default_factory=list)


class DetectionObject(BaseModel):
    """推理返回的单个缺陷目标。"""
    class_id: int
    class_name: str
    class_name_cn: Optional[str] = None
    confidence: float
    bbox: list[float]


class DetectionResponse(BaseModel):
    """单图检测响应。"""
    task_id: int
    public_task_id: str
    status: str
    filename: str
    image_url: str
    annotated_image_url: str
    image_width: int
    image_height: int
    total_objects: int
    inference_time_ms: float
    objects: list[DetectionObject]


class BatchDetectionItem(BaseModel):
    """批量检测中的单文件结果。"""
    file_name: str
    status: str
    total_objects: int = 0
    inference_time_ms: float = 0
    image_url: Optional[str] = None
    annotated_image_url: Optional[str] = None
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    objects: list[DetectionObject] = Field(default_factory=list)
    error: Optional[str] = None


class BatchDetectionResponse(BaseModel):
    """批量检测响应。"""
    task_id: int
    public_task_id: str
    status: str
    source: str = "batch"
    zip_filename: Optional[str] = None
    total_images_in_zip: Optional[int] = None
    success_count: int
    failed_count: int
    items: list[BatchDetectionItem]


# --- 检测统计 ---

class DetectionStatistics(BaseModel):
    training_total_tasks: int = 0
    training_daily_trend: list[dict] = []
    daily_inference_time: list[dict] = Field(default_factory=list)
    """检测统计数据"""
    total_tasks: int
    total_images: int
    total_objects: int
    avg_inference_time: float
    class_distribution: dict[str, int]  # 各类别检测次数
    daily_trend: list[dict]             # 每日检测趋势
    scene_distribution: dict[str, int]  # 各场景检测次数


# ══════════════════════════════════════════════════════════════
# 三、模型管理
# ══════════════════════════════════════════════════════════════

# --- 训练任务 ---

class AdvancedTrainingConfig(BaseModel):
    """Whitelisted Ultralytics 8.3 training options exposed by the UI."""

    model_config = ConfigDict(extra="forbid")

    lrf: float = Field(default=0.01, ge=0, le=1)
    momentum: float = Field(default=0.937, ge=0, le=1)
    weight_decay: float = Field(default=0.0005, ge=0, le=0.1)
    warmup_epochs: float = Field(default=3.0, ge=0, le=20)
    warmup_momentum: float = Field(default=0.8, ge=0, le=1)
    warmup_bias_lr: float = Field(default=0.1, ge=0, le=1)
    patience: int = Field(default=100, ge=0, le=500)
    cos_lr: bool = False
    amp: bool = True
    pretrained: bool = True
    deterministic: bool = True
    seed: int = Field(default=0, ge=0, le=2_147_483_647)
    workers: int = Field(default=8, ge=0, le=64)
    cache: bool = False
    rect: bool = False
    multi_scale: bool = False
    close_mosaic: int = Field(default=10, ge=0, le=500)
    save_period: int = Field(default=-1, ge=-1, le=500)
    freeze: Optional[int] = Field(default=None, ge=0, le=1000)
    mosaic: float = Field(default=1.0, ge=0, le=1)
    mixup: float = Field(default=0.0, ge=0, le=1)
    fliplr: float = Field(default=0.5, ge=0, le=1)
    flipud: float = Field(default=0.0, ge=0, le=1)
    scale: float = Field(default=0.5, ge=0, le=1)
    degrees: float = Field(default=0.0, ge=0, le=180)
    translate: float = Field(default=0.1, ge=0, le=1)
    shear: float = Field(default=0.0, ge=0, le=180)
    perspective: float = Field(default=0.0, ge=0, le=0.001)
    hsv_h: float = Field(default=0.015, ge=0, le=1)
    hsv_s: float = Field(default=0.7, ge=0, le=1)
    hsv_v: float = Field(default=0.4, ge=0, le=1)
    erasing: float = Field(default=0.0, ge=0, le=1)
    label_smoothing: float = Field(default=0.0, ge=0, le=1)
    dropout: float = Field(default=0.0, ge=0, le=1)


class TrainingTaskCreate(BaseModel):
    """创建训练任务"""
    model_config = ConfigDict(protected_namespaces=())

    scene_id: int = Field(..., description="关联场景 ID")
    model_name: str = Field(default="yolov11n", description="基础模型")
    epochs: int = Field(default=100, ge=10, le=500, description="训练轮数")
    img_size: int = Field(default=640, ge=128, le=2048, description="图像尺寸")
    batch_size: int = Field(default=16, ge=1, le=64, description="批次大小")
    device: str = Field(default="cpu", description="训练设备")
    optimizer: Literal["auto", "SGD", "Adam", "AdamW", "NAdam", "RAdam", "RMSProp"] = "SGD"
    lr0: float = Field(default=0.01, gt=0, le=1, description="初始学习率")
    augment_config: Optional[dict] = Field(None, description="兼容旧任务的数据增强配置")
    train_config: Optional[AdvancedTrainingConfig] = Field(None, description="高级训练配置")
    dataset_path: Optional[str] = Field(None, description="数据集目录")


class TrainingDatasetMetadataUpdate(BaseModel):
    """Editable metadata for a user-owned dataset; its directory remains unchanged."""
    display_name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)


class TrainingTaskResponse(BaseModel):
    """训练任务响应"""
    id: int
    public_task_id: str
    user_id: int
    scene_id: int
    scene_name: Optional[str] = None
    task_uuid: str
    status: str
    model_name: str
    epochs: int
    current_epoch: int
    progress: int
    img_size: int
    batch_size: int
    device: str
    optimizer: str = "SGD"
    lr0: float = 0.01
    train_config: Optional[dict] = None
    dataset_size: Optional[int] = None
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    resource_version: int = 1
    deletion_status: str = "active"

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())


class TrainingMetricResponse(BaseModel):
    """训练指标响应（单 epoch）"""
    epoch: int
    box_loss: Optional[float] = None
    cls_loss: Optional[float] = None
    dfl_loss: Optional[float] = None
    precision: Optional[float] = None
    recall: Optional[float] = None
    map50: Optional[float] = None
    map50_95: Optional[float] = None
    lr: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


# --- 模型版本 ---

class ModelVersionBrief(BaseModel):
    """模型版本简要信息"""
    id: int
    version: str
    model_name: str
    model_type: str
    map50: Optional[float] = None
    is_default: bool
    created_at: datetime
    undo_id: Optional[str] = None
    resource_version: int = 1

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())


class ModelVersionResponse(BaseModel):
    """模型版本详情"""
    id: int
    scene_id: int
    scene_name: Optional[str] = None
    training_task_id: Optional[int] = None
    owner_id: Optional[int] = None
    is_builtin: bool = False
    version: str
    model_name: str
    model_type: str
    status: str
    model_path: str
    minio_url: Optional[str] = None
    object_key: Optional[str] = None
    cleanup_pending: bool = False
    cleanup_error: Optional[str] = None
    cleanup_retry_count: int = 0
    map50: Optional[float] = None
    map50_95: Optional[float] = None
    precision: Optional[float] = None
    recall: Optional[float] = None
    per_class_ap: Optional[dict] = None
    description: Optional[str] = None
    file_size: Optional[int] = None
    is_default: bool
    created_at: datetime
    resource_version: int = 1
    deleted_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())


class ModelVersionCreate(BaseModel):
    """手动上传模型版本"""
    model_config = ConfigDict(protected_namespaces=())

    scene_id: int
    version: str = Field(..., description="版本号")
    model_name: str = Field(..., description="模型名称")
    model_type: str = Field(default="yolov11n", description="模型类型")
    description: Optional[str] = None


# --- 模型评估与导出 ---

class ModelValidateRequest(BaseModel):
    """模型评估请求"""
    split: Literal["val", "test", "train"] = Field(
        default="val", description="评估数据集划分: val / test / train"
    )
    conf: float = Field(default=0.001, ge=0, le=1, description="置信度阈值")
    iou: float = Field(default=0.6, ge=0, le=1, description="NMS IoU 阈值")


class ModelExportRequest(BaseModel):
    """模型导出请求"""
    version: Optional[str] = Field(None, description="版本号（如 v1.0.0，不传则自动生成）")
    description: Optional[str] = Field(None, description="版本描述/变更说明")
    set_default: bool = Field(default=False, description="是否设为该场景的默认模型")
    upload_minio: bool = Field(default=True, description="是否上传到 MinIO")


class ModelExportResponse(BaseModel):
    """模型导出响应"""
    model_version_id: int
    version: str
    model_name: str
    model_path: str
    export_dir: str
    minio_url: Optional[str] = None
    file_size: Optional[int] = None
    evaluation: dict
    is_default: bool
    message: str

    model_config = ConfigDict(protected_namespaces=())


class ModelValidateResponse(BaseModel):
    """模型评估响应"""
    task_id: int
    task_uuid: str
    split: str
    overall: dict
    per_class: dict
    model_version_id: Optional[int] = None
    model_version: Optional[str] = None

    model_config = ConfigDict(protected_namespaces=())


# ══════════════════════════════════════════════════════════════
# 四、智能体对话
# ══════════════════════════════════════════════════════════════

class ChatSessionCreate(BaseModel):
    """创建对话会话"""
    title: Optional[str] = None


class ChatSessionResponse(BaseModel):
    """对话会话响应"""
    id: int
    session_uuid: str
    title: Optional[str] = None
    status: str
    message_count: int
    last_message_at: Optional[datetime] = None
    created_at: datetime
    undo_id: Optional[str] = None
    resource_version: int = 1
    deletion_status: str = "active"

    model_config = ConfigDict(from_attributes=True)


class ChatMessageRequest(BaseModel):
    """发送消息请求"""
    session_id: Optional[int] = Field(None, description="会话 ID（为空则自动创建新会话）")
    content: str = Field(..., min_length=1, max_length=5000, description="消息内容")


class ChatMessageResponse(BaseModel):
    """对话消息响应"""
    id: int
    session_id: int
    role: str
    content: str
    agent_used: Optional[str] = None
    tool_calls: Optional[list] = None
    tool_result: Optional[str] = None
    attachments: Optional[list] = None
    image_urls: Optional[list[str]] = None
    has_image: bool = False
    tokens_used: Optional[int] = None
    latency_ms: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatHistoryResponse(BaseModel):
    """对话历史响应（含会话信息和消息列表）"""
    session: ChatSessionResponse
    messages: list[ChatMessageResponse] = []


# ══════════════════════════════════════════════════════════════
# 五、系统运维
# ══════════════════════════════════════════════════════════════

class OperationLogResponse(BaseModel):
    """操作日志响应"""
    id: int
    user_id: Optional[int] = None
    username: Optional[str] = None
    module: str
    action: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    description: Optional[str] = None
    ip_address: Optional[str] = None
    request_method: Optional[str] = None
    request_path: Optional[str] = None
    request_id: Optional[str] = None
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ══════════════════════════════════════════════════════════════
# 六、RAG 知识库
# ══════════════════════════════════════════════════════════════

class KnowledgeDocumentCreate(BaseModel):
    """创建知识文档（原文件已上传至 MinIO 之后调用）"""
    title: str = Field(..., description="文档标题")
    filename: str = Field(..., description="原始文件名")
    file_url: Optional[str] = Field(default=None, description="短期文件访问 URL")
    file_type: Optional[str] = Field(None, description="pdf/docx/txt/md")


class KnowledgeDocumentResponse(BaseModel):
    """知识文档响应"""
    id: int
    user_id: Optional[int] = None
    title: str
    filename: str
    file_url: Optional[str] = None
    object_key: Optional[str] = None
    cleanup_pending: bool = False
    cleanup_error: Optional[str] = None
    cleanup_retry_count: int = 0
    file_type: Optional[str] = None
    status: str
    chunk_count: int
    created_at: datetime
    resource_version: int = 1
    deletion_status: str = "active"
    deleted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ResourceCleanupJobResponse(BaseModel):
    id: int
    resource_type: str
    resource_id: str
    owner_id: Optional[int] = None
    action: str
    status: str
    object_keys: Optional[list[str]] = None
    retry_count: int
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class KnowledgeChunkResponse(BaseModel):
    """知识分块响应（不含 embedding 向量本身，体积大且前端用不上）"""
    id: int
    document_id: int
    chunk_index: int
    content: str
    token_count: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class KnowledgeSearchRequest(BaseModel):
    """RAG 相似度检索请求"""
    query: str = Field(..., min_length=1, description="检索问题原文，后端负责转 embedding")
    top_k: int = Field(default=5, ge=1, le=20, description="返回最相似的分块数量")
    document_id: Optional[int] = Field(None, description="限定在某一篇文档内检索")


# ══════════════════════════════════════════════════════════════
# 七、通用模型
# ══════════════════════════════════════════════════════════════

class ApiResponse(BaseModel):
    """统一 API 响应"""
    code: int = 200
    message: str = "success"
    data: Optional[dict | list] = None


class PageParams(BaseModel):
    """分页查询参数"""
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=20, ge=1, le=100, description="每页数量")


class PageResponse(BaseModel):
    """分页响应"""
    total: int
    page: int
    page_size: int
    total_pages: int
    items: list


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str = "healthy"
    app_name: str
    version: str
    database: Optional[str] = None
    redis: Optional[str] = None
    minio: Optional[str] = None
