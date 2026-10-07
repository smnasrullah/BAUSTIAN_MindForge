"""van_plans + van_routes + van_stops (F14 van route optimizer, advisory)

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-06
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TSTZ = sa.DateTime(timezone=True)
BIGINT_PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
MONEY = sa.Numeric(14, 2)
PLAN_STATUS = "status IN ('pending', 'approved', 'rejected', 'superseded')"
STOP_STATUS = "status IN ('planned', 'dropped', 'delivered')"


def upgrade() -> None:
    op.create_table(
        "van_plans",
        sa.Column("id", BIGINT_PK, primary_key=True, autoincrement=True),
        sa.Column("distributor_id", sa.Integer(),
                  sa.ForeignKey("distributors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("clock_origin", TSTZ, nullable=False),
        sa.Column("planned_at", TSTZ, nullable=False),
        sa.Column("horizon_h", sa.SmallInteger(), nullable=False),
        sa.Column("params", JSON, nullable=False),
        sa.Column("objective", JSON, nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("input_hash", sa.Text(), nullable=False),
        sa.Column("distance_source", sa.Text(), nullable=False),
        sa.Column("solver", sa.Text(), nullable=False),
        sa.Column("stopped_by", sa.Text(), nullable=False),
        sa.Column("solve_ms", sa.Integer(), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decided_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", TSTZ, nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", TSTZ, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(PLAN_STATUS, name="ck_van_plans_status"),
    )
    op.create_index("ix_van_plans_distributor_created", "van_plans",
                    ["distributor_id", "created_at"])
    op.create_index("ix_van_plans_distributor_hash", "van_plans", ["distributor_id", "input_hash"])
    op.create_table(
        "van_routes",
        sa.Column("id", BIGINT_PK, primary_key=True, autoincrement=True),
        sa.Column("plan_id", BIGINT_PK, sa.ForeignKey("van_plans.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("vehicle_no", sa.SmallInteger(), nullable=False),
        sa.Column("km", sa.Numeric(10, 2), nullable=False),
        sa.Column("minutes", sa.Numeric(10, 1), nullable=False),
        sa.Column("cash_load", MONEY, nullable=False),
        sa.Column("cost_bdt", MONEY, nullable=False),
        sa.Column("legs", JSON, nullable=False),
    )
    op.create_index("ix_van_routes_plan", "van_routes", ["plan_id"])
    op.create_table(
        "van_stops",
        sa.Column("id", BIGINT_PK, primary_key=True, autoincrement=True),
        sa.Column("plan_id", BIGINT_PK, sa.ForeignKey("van_plans.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("route_id", BIGINT_PK, sa.ForeignKey("van_routes.id", ondelete="CASCADE"),
                  nullable=True),
        sa.Column("seq", sa.SmallInteger(), nullable=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("recommendation_id", sa.BigInteger(), nullable=True),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("eta_lo", TSTZ, nullable=True),
        sa.Column("eta_hi", TSTZ, nullable=True),
        sa.Column("deadline", TSTZ, nullable=True),
        sa.Column("penalty_bdt", MONEY, nullable=False),
        sa.Column("source_quantile", sa.Text(), nullable=False),
        sa.Column("stockout_before_arrival_p", sa.Numeric(8, 4), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("details", JSON, nullable=False),
        sa.Column("delivered_at", TSTZ, nullable=True),
        sa.Column("delivered_amount", MONEY, nullable=True),
        sa.CheckConstraint(STOP_STATUS, name="ck_van_stops_status"),
    )
    op.create_index("ix_van_stops_plan", "van_stops", ["plan_id"])
    op.create_index("ix_van_stops_agent", "van_stops", ["agent_id"])


def downgrade() -> None:
    op.drop_table("van_stops")
    op.drop_table("van_routes")
    op.drop_table("van_plans")
