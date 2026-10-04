"""merge release heads and backfill the shipped dataset

Revision ID: b2c3d4e5f6a7
Revises: 9f1b2c3d4e5f
"""

from alembic import op


revision = "b2c3d4e5f6a7"
down_revision = "9f1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE training_datasets "
        "SET is_builtin = true, owner_id = NULL "
        "WHERE path = 'NEU-DET.v9i.yolov11'"
    )


def downgrade() -> None:
    # The merge is structural and the builtin marker is intentionally retained.
    pass
