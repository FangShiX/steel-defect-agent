"""add complete advanced training configuration

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
"""

from alembic import op
import sqlalchemy as sa


revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("training_tasks", sa.Column("train_config", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("training_tasks", "train_config")
