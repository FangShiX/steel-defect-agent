"""persist multiple chat attachment paths

Revision ID: 8d2e4f6a9b1c
Revises: 7c9e1a2b3d4e
Create Date: 2026-07-16
"""

from alembic import op
import sqlalchemy as sa

revision = "8d2e4f6a9b1c"
down_revision = "7c9e1a2b3d4e"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("image_paths", sa.JSON(), nullable=True))

def downgrade() -> None:
    op.drop_column("chat_messages", "image_paths")
