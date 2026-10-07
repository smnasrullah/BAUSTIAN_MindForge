"""Index forecasts(model_version_id, generated_at).

GET /system/freshness (polled by every signed-in tab) reads max(generated_at) for the active
model version; without this index it was a sequential scan over all forecast rows.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-03
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IX = "ix_forecasts_version_generated"


def upgrade() -> None:
    op.create_index(IX, "forecasts", ["model_version_id", "generated_at"])


def downgrade() -> None:
    op.drop_index(IX, table_name="forecasts")
