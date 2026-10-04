"""add request and task/session correlation to audit logs"""

from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("request_id", "task_id", "session_id"):
        op.add_column("operation_logs", sa.Column(name, sa.String(length=100), nullable=True))
        op.create_index(f"ix_operation_logs_{name}", "operation_logs", [name])


def downgrade() -> None:
    for name in ("session_id", "task_id", "request_id"):
        op.drop_index(f"ix_operation_logs_{name}", table_name="operation_logs")
        op.drop_column("operation_logs", name)
