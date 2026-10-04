"""Merge the legacy chat-image branch with the current feature chain."""

from alembic import op


revision = "f7b8c9d0e1f2"
down_revision = ("8d2e4f6a9b1c", "f6a7b8c9d0e1")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
