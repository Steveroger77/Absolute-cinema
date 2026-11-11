"""Add Google OAuth fields and make password_hash nullable on users.

Revision ID: 0002_add_google_oauth
Revises: 0001_initial_schema
Create Date: 2026-11-11
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002_add_google_oauth"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "password_hash",
            existing_type=sa.String(length=255),
            nullable=True,
        )
        batch_op.add_column(sa.Column("google_sub", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("avatar_url", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "auth_provider",
                sa.String(length=24),
                nullable=False,
                server_default="local",
            )
        )
        batch_op.create_index("ix_users_google_sub", ["google_sub"], unique=True)


def downgrade() -> None:
    op.execute("UPDATE users SET password_hash = '!google-oauth-only' WHERE password_hash IS NULL")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_google_sub")
        batch_op.drop_column("auth_provider")
        batch_op.drop_column("avatar_url")
        batch_op.drop_column("google_sub")
        batch_op.alter_column(
            "password_hash",
            existing_type=sa.String(length=255),
            nullable=False,
        )
