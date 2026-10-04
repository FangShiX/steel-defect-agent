"""add stable object keys and cleanup tracking"""
from alembic import op
import sqlalchemy as sa

revision = "9f1b2c3d4e5f"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None

def upgrade():
    for table, columns in {
        "model_versions": [sa.Column("object_key", sa.String(500)), sa.Column("cleanup_pending", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("cleanup_error", sa.Text()), sa.Column("cleanup_retry_count", sa.Integer(), nullable=False, server_default="0")],
        "knowledge_documents": [sa.Column("object_key", sa.String(500)), sa.Column("cleanup_pending", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("cleanup_error", sa.Text()), sa.Column("cleanup_retry_count", sa.Integer(), nullable=False, server_default="0")],
        "detection_results": [sa.Column("original_object_key", sa.String(500)), sa.Column("annotated_object_key", sa.String(500)), sa.Column("cleanup_pending", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("cleanup_error", sa.Text()), sa.Column("cleanup_retry_count", sa.Integer(), nullable=False, server_default="0")],
        "training_datasets": [sa.Column("display_name", sa.String(200)), sa.Column("description", sa.Text())],
    }.items():
        for column in columns:
            op.add_column(table, column)

def downgrade():
    for table, names in {"training_datasets": ["description", "display_name"], "detection_results": ["cleanup_retry_count", "cleanup_error", "cleanup_pending", "annotated_object_key", "original_object_key"], "knowledge_documents": ["cleanup_retry_count", "cleanup_error", "cleanup_pending", "object_key"], "model_versions": ["cleanup_retry_count", "cleanup_error", "cleanup_pending", "object_key"]}.items():
        for name in names:
            op.drop_column(table, name)
