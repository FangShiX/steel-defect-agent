"""add short-lived undo actions

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
"""
from alembic import op
import sqlalchemy as sa

revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "undo_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("undo_uuid", sa.String(length=100), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operation", sa.String(length=80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_undo_actions_undo_uuid", "undo_actions", ["undo_uuid"], unique=True)
    op.create_index("ix_undo_actions_user_id", "undo_actions", ["user_id"])
    op.create_index("ix_undo_actions_operation", "undo_actions", ["operation"])
    op.create_index("ix_undo_actions_expires_at", "undo_actions", ["expires_at"])


def downgrade():
    op.drop_table("undo_actions")
