"""add durable high-risk action confirmations"""

from alembic import op
import sqlalchemy as sa

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "action_confirmations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("confirmation_uuid", sa.String(length=100), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=80), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_id", sa.String(length=120), nullable=True),
        sa.Column("impact", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("task_id", sa.String(length=100), nullable=True),
        sa.Column("session_id", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("confirmation_uuid"),
    )
    for name in ("user_id", "operation", "status", "request_id", "task_id", "session_id"):
        op.create_index(f"ix_action_confirmations_{name}", "action_confirmations", [name])


def downgrade() -> None:
    op.drop_table("action_confirmations")
