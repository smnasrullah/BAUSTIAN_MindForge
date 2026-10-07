"""rate_limit_hits: sliding-window security limits shared by all API worker processes.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-03
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_hits",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column("bucket", sa.Text(), nullable=False),
        sa.Column("hit_at", sa.Double(), nullable=False),
    )
    op.create_index("ix_rate_limit_hits_bucket_at", "rate_limit_hits", ["bucket", "hit_at"])


def downgrade() -> None:
    op.drop_index("ix_rate_limit_hits_bucket_at", table_name="rate_limit_hits")
    op.drop_table("rate_limit_hits")
