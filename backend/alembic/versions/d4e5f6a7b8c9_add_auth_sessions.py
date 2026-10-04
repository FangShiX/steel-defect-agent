"""add server-side authentication sessions"""

from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a7b8c9"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_uuid", sa.String(length=100), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("access_jti", sa.String(length=100), nullable=False),
        sa.Column("refresh_jti", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("access_expires_at", sa.DateTime(), nullable=False),
        sa.Column("refresh_expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("ip_address", sa.String(length=50), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_uuid"),
        sa.UniqueConstraint("access_jti"),
        sa.UniqueConstraint("refresh_jti"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_access_jti", "auth_sessions", ["access_jti"])
    op.create_index("ix_auth_sessions_refresh_jti", "auth_sessions", ["refresh_jti"])
    op.create_index("ix_auth_sessions_revoked_at", "auth_sessions", ["revoked_at"])


def downgrade() -> None:
    op.drop_table("auth_sessions")
