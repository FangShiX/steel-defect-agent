"""persist image paths for chat history

Revision ID: 4f7e40ed7a2c
Revises: 0732a4fd01e5
Create Date: 2026-07-16
"""

from alembic import op
import sqlalchemy as sa


revision = "4f7e40ed7a2c"
down_revision = "0732a4fd01e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("image_path", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_messages", "image_path")
