"""add stored_files lifecycle ledger"""
from alembic import op
import sqlalchemy as sa

revision = "9f4e2a1c7b6d"
down_revision = "a41004b06801"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stored_files",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("object_key", sa.String(length=500), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=True),
        sa.Column("resource_type", sa.String(length=50), nullable=False),
        sa.Column("resource_id", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("cleanup_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
    )
    op.create_index("ix_stored_files_user_id", "stored_files", ["user_id"])
    op.create_index("ix_stored_files_object_key", "stored_files", ["object_key"])
    op.create_index("ix_stored_files_status", "stored_files", ["status"])
    op.create_index("ix_stored_files_created_at", "stored_files", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_stored_files_created_at", table_name="stored_files")
    op.drop_index("ix_stored_files_status", table_name="stored_files")
    op.drop_index("ix_stored_files_object_key", table_name="stored_files")
    op.drop_index("ix_stored_files_user_id", table_name="stored_files")
    op.drop_table("stored_files")
