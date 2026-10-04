"""
MinIO 对象存储客户端封装
用于存储检测图像、训练模型等文件
"""
import io
import logging
from minio import Minio
from minio.error import S3Error

from app.config.settings import settings

logger = logging.getLogger(__name__)


def object_key_from_url(value: str) -> str | None:
    from urllib.parse import unquote, urlparse

    path = unquote(urlparse(value).path).lstrip("/")
    if path.startswith("api/storage/"):
        path = path[len("api/storage/"):]
    bucket, separator, key = path.partition("/")
    return key if separator and bucket == settings.MINIO_BUCKET else None


class MinIOClient:
    """MinIO 客户端封装"""

    def __init__(self):
        self.client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        self.bucket_name = settings.MINIO_BUCKET
        self._ensure_bucket()

    def _ensure_bucket(self):
        """确保存储桶存在，不存在则创建"""
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
        except S3Error as e:
            print(f"MinIO bucket 初始化警告: {e}")

    def upload_file(self, object_name: str, file_path: str) -> str:
        """
        上传本地文件到 MinIO

        Args:
            object_name: MinIO 中的对象名称（路径）
            file_path: 本地文件路径

        Returns:
            预签名 URL
        """
        self.client.fput_object(
            bucket_name=self.bucket_name,
            object_name=object_name,
            file_path=file_path,
        )
        return self.get_presigned_url(object_name)

    def upload_bytes(self, object_name: str, data: bytes, content_type: str = "image/jpeg") -> str:
        """
        上传字节数据到 MinIO

        Args:
            object_name: MinIO 中的对象名称
            data: 字节数据
            content_type: MIME 类型

        Returns:
            预签名 URL
        """
        self.client.put_object(
            bucket_name=self.bucket_name,
            object_name=object_name,
            data=io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        return self.get_presigned_url(object_name)

    def get_presigned_url(self, object_name: str, expires_seconds: int = 15 * 60) -> str:
        """获取对象的预签名访问 URL（默认有效期 15 分钟）"""
        from datetime import datetime, timedelta, timezone
        from urllib.parse import quote
        import jwt

        # Keep the storage service private. A scoped, short-lived URL is served
        # by the authenticated application's gateway, not an internal hostname.
        token = jwt.encode({"aud": "storage", "bucket": self.bucket_name, "object": object_name,
                            "exp": datetime.now(timezone.utc) + timedelta(seconds=expires_seconds)},
                           settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
        return f"/api/storage/{quote(self.bucket_name, safe='')}/{quote(object_name, safe='/')}?token={token}"

    def delete_file(self, object_name: str):
        """删除 MinIO 中的文件"""
        self.client.remove_object(
            bucket_name=self.bucket_name,
            object_name=object_name,
        )

    def delete_by_url(self, url: str | None, *, suppress_errors: bool = True):
        """
        按已保存的（预签名）URL 删除文件，删除类服务里统一调这个方法即可。
        从 URL 中解析出 bucket 之后的 object_name 部分。默认兼容旧调用静默记录错误；
        资源清理事务应传 suppress_errors=False，让上层生成可审计的重试任务。
        """
        if not url:
            return
        try:
            object_name = object_key_from_url(url)
            if object_name:
                self.delete_file(object_name)
        except Exception:
            logger.exception("MinIO cleanup failed for a stored object reference")
            raise

    def object_exists(self, object_name: str) -> bool:
        try:
            self.client.stat_object(self.bucket_name, object_name)
            return True
        except S3Error:
            return False

    def list_objects(self, prefix: str = ""):
        return self.client.list_objects(self.bucket_name, prefix=prefix, recursive=True)
