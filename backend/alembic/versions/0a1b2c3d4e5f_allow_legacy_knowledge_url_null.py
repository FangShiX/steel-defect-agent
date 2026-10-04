"""Allow knowledge documents to omit legacy permanent URLs."""

from alembic import op
import sqlalchemy as sa


revision = "0a1b2c3d4e5f"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_documents") as batch_op:
        batch_op.alter_column(
            "file_url",
            existing_type=sa.String(length=500),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_documents") as batch_op:
        batch_op.alter_column(
            "file_url",
            existing_type=sa.String(length=500),
            nullable=False,
        )
