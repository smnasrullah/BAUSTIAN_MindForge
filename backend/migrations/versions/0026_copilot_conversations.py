"""copilot_conversation + copilot_message (persistent, per-user copilot history)

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-07
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TSTZ = sa.DateTime(timezone=True)
BIGINT_PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "copilot_conversation",
        sa.Column("id", BIGINT_PK, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("created_at", TSTZ, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TSTZ, server_default=sa.func.now(), nullable=False),
        sa.Column("state_json", JSON, nullable=False),
    )
    op.create_index("ix_copilot_conversation_user_updated", "copilot_conversation",
                    ["user_id", "updated_at"])
    op.create_table(
        "copilot_message",
        sa.Column("id", BIGINT_PK, primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
                  sa.ForeignKey("copilot_conversation.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", TSTZ, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_copilot_message_role"),
    )
    op.create_index("ix_copilot_message_conversation", "copilot_message",
                    ["conversation_id", "id"])


def downgrade() -> None:
    op.drop_table("copilot_message")
    op.drop_table("copilot_conversation")
