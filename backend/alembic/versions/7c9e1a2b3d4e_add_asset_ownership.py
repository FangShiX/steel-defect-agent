"""add model and dataset asset ownership

Revision ID: 7c9e1a2b3d4e
Revises: 4f7e40ed7a2c
Create Date: 2026-07-16
"""

from alembic import op
import sqlalchemy as sa


revision = "7c9e1a2b3d4e"
down_revision = "4f7e40ed7a2c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_versions", sa.Column("owner_id", sa.Integer(), nullable=True))
    op.add_column("model_versions", sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_foreign_key("fk_model_versions_owner_id_users", "model_versions", "users", ["owner_id"], ["id"])
    op.create_index("ix_model_versions_owner_id", "model_versions", ["owner_id"])
    op.execute("UPDATE model_versions SET owner_id = training_tasks.user_id FROM training_tasks WHERE model_versions.training_task_id = training_tasks.id")
    op.execute("UPDATE model_versions SET is_builtin = true, owner_id = NULL WHERE training_task_id IS NULL AND model_name = 'ssdd_yolo11n_v1'")
    op.create_table(
        "training_datasets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("path", sa.String(length=500), nullable=False, unique=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_training_datasets_owner_id", "training_datasets", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_training_datasets_owner_id", table_name="training_datasets")
    op.drop_table("training_datasets")
    op.drop_index("ix_model_versions_owner_id", table_name="model_versions")
    op.drop_constraint("fk_model_versions_owner_id_users", "model_versions", type_="foreignkey")
    op.drop_column("model_versions", "is_builtin")
    op.drop_column("model_versions", "owner_id")
