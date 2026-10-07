"""stockout_predictions: refill-aware view (additional, not the decision input)

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable: caches built before this revision (or by the old method) have no refill view.
    op.add_column("stockout_predictions",
                  sa.Column("refill_hours_to_stockout", sa.Numeric(6, 2), nullable=True))
    op.add_column("stockout_predictions",
                  sa.Column("refill_prob_24h", sa.Numeric(8, 4), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("stockout_predictions") as batch:
        batch.drop_column("refill_prob_24h")
        batch.drop_column("refill_hours_to_stockout")
