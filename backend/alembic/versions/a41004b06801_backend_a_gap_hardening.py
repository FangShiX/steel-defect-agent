"""add backend-A ownership, lifecycle and cleanup metadata

This migration follows the latest dev migration chain.  The older PR draft
used revision b2c3d4e5f6a7, which is already occupied by dev.
"""

from alembic import op
import sqlalchemy as sa


revision = "a41004b06801"
down_revision = "0a1b2c3d4e5f"
branch_labels = None
depends_on = None


def _lifecycle_columns(table: str, *, cleanup: bool = False) -> None:
    op.add_column(table, sa.Column("resource_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column(table, sa.Column("deletion_status", sa.String(length=20), nullable=False, server_default="active"))
    op.add_column(table, sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.add_column(table, sa.Column("deleted_by_id", sa.Integer(), nullable=True))
    op.add_column(table, sa.Column("purge_after", sa.DateTime(), nullable=True))
    if cleanup:
        op.add_column(table, sa.Column("cleanup_retry_count", sa.Integer(), nullable=False, server_default="0"))
        op.add_column(table, sa.Column("cleanup_error", sa.Text(), nullable=True))
    op.create_foreign_key(
        f"fk_{table}_deleted_by_id_users", table, "users", ["deleted_by_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index(f"ix_{table}_deletion_status", table, ["deletion_status"])


def upgrade() -> None:
    for table, prefix in (("detection_tasks", "det"), ("training_tasks", "trn")):
        op.add_column(table, sa.Column("public_task_id", sa.String(length=24), nullable=True))
        op.add_column(table, sa.Column("idempotency_key", sa.String(length=128), nullable=True))
        op.execute(
            f"UPDATE {table} SET public_task_id = '{prefix}_' || "
            "substr(md5(random()::text || clock_timestamp()::text || id::text), 1, 16) "
            "WHERE public_task_id IS NULL"
        )
        op.alter_column(table, "public_task_id", nullable=False)
        op.create_index(f"ix_{table}_public_task_id", table, ["public_task_id"], unique=True)
        op.create_unique_constraint(f"uq_{table}_user_idempotency", table, ["user_id", "idempotency_key"])

    _lifecycle_columns("detection_tasks", cleanup=True)
    _lifecycle_columns("training_tasks", cleanup=True)

    # origin/dev already added display_name and the cleanup columns in 9f1b2c3d4e5f.
    op.add_column("training_datasets", sa.Column("storage_key", sa.String(length=500), nullable=True))
    op.add_column("training_datasets", sa.Column("idempotency_key", sa.String(length=128), nullable=True))
    op.execute("UPDATE training_datasets SET display_name = COALESCE(display_name, path), storage_key = path")
    op.alter_column("training_datasets", "display_name", nullable=False)
    op.alter_column("training_datasets", "storage_key", nullable=False)
    op.create_index("ix_training_datasets_storage_key", "training_datasets", ["storage_key"], unique=True)
    op.create_unique_constraint(
        "uq_training_datasets_owner_idempotency", "training_datasets", ["owner_id", "idempotency_key"]
    )
    _lifecycle_columns("training_datasets", cleanup=False)

    # origin/dev already added the model cleanup retry columns in 9f1b2c3d4e5f.
    for column in (
        sa.Column("resource_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_by_id", sa.Integer(), nullable=True),
        sa.Column("purge_after", sa.DateTime(), nullable=True),
    ):
        op.add_column("model_versions", column)
    op.create_foreign_key(
        "fk_model_versions_deleted_by_id_users", "model_versions", "users", ["deleted_by_id"], ["id"], ondelete="SET NULL"
    )
    op.execute(
        "WITH ranked AS (SELECT id, row_number() OVER (PARTITION BY scene_id ORDER BY id DESC) AS rn "
        "FROM model_versions WHERE is_default = true AND status = 'active') "
        "UPDATE model_versions SET is_default = false WHERE id IN (SELECT id FROM ranked WHERE rn > 1)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_model_versions_one_default_per_scene "
        "ON model_versions (scene_id) WHERE is_default = true AND status = 'active'"
    )

    _lifecycle_columns("knowledge_documents", cleanup=False)
    _lifecycle_columns("chat_sessions")

    op.create_table(
        "resource_cleanup_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("resource_type", sa.String(length=50), nullable=False),
        sa.Column("resource_id", sa.String(length=100), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=30), nullable=False, server_default="purge"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("object_keys", sa.JSON(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
    )
    for column in ("resource_type", "resource_id", "owner_id", "status"):
        op.create_index(f"ix_resource_cleanup_jobs_{column}", "resource_cleanup_jobs", [column])


def downgrade() -> None:
    for column in ("status", "owner_id", "resource_id", "resource_type"):
        op.drop_index(f"ix_resource_cleanup_jobs_{column}", table_name="resource_cleanup_jobs")
    op.drop_table("resource_cleanup_jobs")
    for table, cleanup in (("chat_sessions", False), ("knowledge_documents", False), ("training_datasets", False), ("training_tasks", True), ("detection_tasks", True)):
        _drop_lifecycle_columns(table, cleanup=cleanup)
    op.drop_constraint("fk_model_versions_deleted_by_id_users", "model_versions", type_="foreignkey")
    op.execute("DROP INDEX IF EXISTS uq_model_versions_one_default_per_scene")
    for column in ("purge_after", "deleted_by_id", "deleted_at", "resource_version"):
        op.drop_column("model_versions", column)
    op.drop_constraint("uq_training_datasets_owner_idempotency", "training_datasets", type_="unique")
    op.drop_index("ix_training_datasets_storage_key", table_name="training_datasets")
    op.drop_column("training_datasets", "idempotency_key")
    op.drop_column("training_datasets", "storage_key")
    for table in ("training_tasks", "detection_tasks"):
        op.drop_constraint(f"uq_{table}_user_idempotency", table, type_="unique")
        op.drop_index(f"ix_{table}_public_task_id", table_name=table)
        op.drop_column(table, "idempotency_key")
        op.drop_column(table, "public_task_id")


def _drop_lifecycle_columns(table: str, *, cleanup: bool = False) -> None:
    op.drop_index(f"ix_{table}_deletion_status", table_name=table)
    op.drop_constraint(f"fk_{table}_deleted_by_id_users", table, type_="foreignkey")
    if cleanup:
        op.drop_column(table, "cleanup_error")
        op.drop_column(table, "cleanup_retry_count")
    op.drop_column(table, "purge_after")
    op.drop_column(table, "deleted_by_id")
    op.drop_column(table, "deleted_at")
    op.drop_column(table, "deletion_status")
    op.drop_column(table, "resource_version")
