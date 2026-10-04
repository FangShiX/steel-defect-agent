"""
Embedding 服务 — 把文本转成向量，供 RAG 知识库入库 / 检索使用

复用 openai SDK 调用 OpenAI 兼容的 /embeddings 接口（DashScope、SiliconFlow 等国内
供应商大多兼容这个协议）。EMBEDDING_MODEL 输出的向量维度必须和
app/entity/db_models.py 里的 EMBEDDING_DIM 一致，否则写入 knowledge_chunks 时
pgvector 会直接报维度不匹配的错误。
"""
from fastapi import HTTPException
from openai import OpenAI

from app.config.settings import settings
from app.core.logger import get_logger
from app.entity.db_models import EMBEDDING_DIM

logger = get_logger(__name__)


class EmbeddingService:
    """文本向量化服务"""

    def __init__(self):
        self._client: OpenAI | None = None

    def _get_client(self) -> OpenAI:
        if not settings.embedding_api_key:
            raise HTTPException(
                status_code=503,
                detail="未配置 EMBEDDING_API_KEY / OPENAI_API_KEY，无法调用向量化接口",
            )
        if self._client is None:
            self._client = OpenAI(
                api_key=settings.embedding_api_key,
                base_url=settings.embedding_base_url,
            )
        return self._client

    def embed_text(self, text: str) -> list[float]:
        """将单段文本转为向量"""
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量把文本转为向量，输入为空列表时直接返回空列表"""
        if not texts:
            return []
        client = self._get_client()
        try:
            resp = client.embeddings.create(
                model=settings.EMBEDDING_MODEL,
                input=texts,
                dimensions=EMBEDDING_DIM,
            )
        except Exception as exc:
            logger.warning("Embedding 调用失败: %s", exc)
            raise HTTPException(status_code=502, detail="向量化失败，请稍后重试") from exc

        vectors = [item.embedding for item in resp.data]
        for vec in vectors:
            if len(vec) != EMBEDDING_DIM:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"Embedding 模型 {settings.EMBEDDING_MODEL} 输出维度 {len(vec)} "
                        f"与 knowledge_chunks 表定义的 EMBEDDING_DIM={EMBEDDING_DIM} 不一致，"
                        "请检查 EMBEDDING_MODEL 配置或数据库表结构"
                    ),
                )
        return vectors


# 全局单例
embedding_service = EmbeddingService()
