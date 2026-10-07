"""llm_intent: van_narrative (van plan wording through the guarded LLM service)

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-06
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_pg() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    # SQLite stores the enum as plain text (non-native), so only Postgres needs the new value.
    if _is_pg():
        op.execute("ALTER TYPE llm_intent ADD VALUE IF NOT EXISTS 'van_narrative'")


def downgrade() -> None:
    # Postgres cannot drop one enum value; rows using it are removed, the value stays unused.
    op.execute("DELETE FROM llm_cache WHERE intent = 'van_narrative'")
    op.execute("DELETE FROM llm_call_log WHERE intent = 'van_narrative'")
