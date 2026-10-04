"""add password reset and knowledge base tables

Revision ID: a1b2c3d4e5f6
Revises: 0732a4fd01e5
Create Date: 2026-07-15 16:30:00.000000

新增三张表：
- password_reset_tokens：忘记密码流程使用的一次性令牌
- knowledge_documents：RAG 知识库的原始文档元数据
- knowledge_chunks：文档切分后的文本块及向量表示

这三张表之前是通过 Base.metadata.create_all() 顺带建的，没有对应的 Alembic
迁移文件；本迁移把它们纳入 Alembic 管理，确保云端部署时能在空库上正确建出来。

down_revision 接在 4f7e40ed7a2c（chat_messages.image_path）之后——本迁移最初是在
该迁移出现之前独立开发的，合并到主分支时把 down_revision 重定到了当前链路的最新头。

注意：
- knowledge_chunks.embedding 使用 pgvector 扩展的 VECTOR 类型，迁移开始时
  会先执行 CREATE EXTENSION IF NOT EXISTS vector
- knowledge_chunks 还额外建了一个 ivfflat 向量索引，供 RAG 相似度检索使用
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "8d2e4f6a9b1c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# knowledge_chunks.embedding 的向量维度（与 db_models.py 里的 EMBEDDING_DIM 保持一致）
EMBEDDING_DIM = 768


def upgrade() -> None:
    # ── 0. pgvector 扩展 ────────────────────────────────────────
    # knowledge_chunks.embedding 是 VECTOR 类型，必须先启用扩展。
    # 用 IF NOT EXISTS 保证重跑不报错。
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── 1. password_reset_tokens ────────────────────────────────
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False, comment="所属用户"),
        sa.Column("token_hash", sa.String(length=64), nullable=False, comment="SHA256 哈希后的令牌值"),
        sa.Column("expires_at", sa.DateTime(), nullable=False, comment="过期时间"),
        sa.Column("used", sa.Boolean(), nullable=True, comment="是否已使用"),
        sa.Column("created_at", sa.DateTime(), nullable=True, comment="创建时间"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_password_reset_tokens_token_hash", "password_reset_tokens", ["token_hash"])
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])

    # ── 2. knowledge_documents ──────────────────────────────────
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True, comment="上传者，为空表示系统内置文档"),
        sa.Column("title", sa.String(length=200), nullable=False, comment="文档标题"),
        sa.Column("filename", sa.String(length=255), nullable=False, comment="原始文件名"),
        sa.Column("file_url", sa.String(length=500), nullable=False, comment="MinIO 原文件 URL"),
        sa.Column("file_type", sa.String(length=20), nullable=True, comment="pdf/docx/txt/md"),
        sa.Column("status", sa.String(length=20), nullable=True, comment="processing/indexed/failed"),
        sa.Column("chunk_count", sa.Integer(), nullable=True, comment="分块完成后的块数"),
        sa.Column("created_at", sa.DateTime(), nullable=True, comment="上传时间"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_documents_status", "knowledge_documents", ["status"])
    op.create_index("ix_knowledge_documents_user_id", "knowledge_documents", ["user_id"])

    # ── 3. knowledge_chunks ─────────────────────────────────────
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False, comment="所属文档"),
        sa.Column("chunk_index", sa.Integer(), nullable=False, comment="块在文档中的序号"),
        sa.Column("content", sa.Text(), nullable=False, comment="分块原文"),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False, comment="向量表示，用于相似度检索"),
        sa.Column("token_count", sa.Integer(), nullable=True, comment="该块 token 数"),
        sa.Column("created_at", sa.DateTime(), nullable=True, comment="创建时间"),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])

    # ── 4. 向量相似度检索索引 (ivfflat) ─────────────────────────
    # ivfflat 需要预先聚类，lists 参数控制聚类数量。100 是 pgvector 官方
    # 建议的小数据量默认值，等未来数据量涨到 100 万级再考虑改为 hnsw 索引。
    op.execute(
        "CREATE INDEX ix_knowledge_chunks_embedding "
        "ON knowledge_chunks USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )


def downgrade() -> None:
    # 按建表反序删除（先删被引用的子表 knowledge_chunks，再删父表 knowledge_documents）
    # 向量索引会随表删除自动清掉，无需手动 drop_index
    op.drop_table("knowledge_chunks")

    op.drop_index("ix_knowledge_documents_user_id", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_status", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")

    op.drop_index("ix_password_reset_tokens_user_id", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_token_hash", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")

    # 不主动删除 pgvector 扩展：其他项目可能也在用同一个数据库实例
    # 如果确认独占，可以手动执行 DROP EXTENSION vector CASCADE
