"""add dataset archive status

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
"""
from alembic import op
import sqlalchemy as sa

revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("training_datasets", sa.Column("status", sa.String(length=20), nullable=False, server_default="active"))
    op.create_index("ix_training_datasets_status", "training_datasets", ["status"])


def downgrade():
    op.drop_index("ix_training_datasets_status", table_name="training_datasets")
    op.drop_column("training_datasets", "status")
