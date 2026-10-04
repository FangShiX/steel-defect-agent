"""persist non-image chat attachments"""

from alembic import op
import sqlalchemy as sa

revision = "c4d5e6f7a8b9"
down_revision = "f7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("attachments", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_messages", "attachments")
