"""add durable notifications

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
"""
from alembic import op
import sqlalchemy as sa

revision = "a7b8c9d0e1f2"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("task_id", sa.String(length=100), nullable=True),
        sa.Column("resource_type", sa.String(length=80), nullable=True),
        sa.Column("resource_id", sa.String(length=120), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for name, column in (
        ("ix_notifications_user_id", "user_id"),
        ("ix_notifications_kind", "kind"),
        ("ix_notifications_task_id", "task_id"),
        ("ix_notifications_request_id", "request_id"),
        ("ix_notifications_read_at", "read_at"),
        ("ix_notifications_created_at", "created_at"),
    ):
        op.create_index(name, "notifications", [column])


def downgrade():
    op.drop_table("notifications")
