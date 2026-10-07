"""Van plans (F14): one optimised plan per distributor request; a human approves or rejects it.

Advisory only: nothing here moves money. Decisions and deliveries are also written to audit_log.
Dropped stops have no route (route_id NULL) but always a reason; see app/rules/van_routing.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BigIntPK, JsonDoc, Money, Ratio, TsTz, created_at_col

PLAN_STATUSES = ("pending", "approved", "rejected", "superseded")
STOP_STATUSES = ("planned", "dropped", "delivered")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class VanPlan(Base):
    __tablename__ = "van_plans"
    __table_args__ = (
        CheckConstraint(_in("status", PLAN_STATUSES), name="ck_van_plans_status"),
        Index("ix_van_plans_distributor_created", "distributor_id", "created_at"),
        Index("ix_van_plans_distributor_hash", "distributor_id", "input_hash"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    distributor_id: Mapped[int] = mapped_column(
        ForeignKey("distributors.id", ondelete="CASCADE"))
    clock_origin: Mapped[datetime] = mapped_column(TsTz)  # forecast origin the inputs came from
    planned_at: Mapped[datetime] = mapped_column(TsTz)  # wall clock: the vans leave now
    horizon_h: Mapped[int] = mapped_column(SmallInteger)
    params: Mapped[dict[str, Any]] = mapped_column(JsonDoc, default=dict)
    objective: Mapped[dict[str, Any]] = mapped_column(JsonDoc, default=dict)
    status: Mapped[str] = mapped_column(Text, default="pending", server_default="pending")
    input_hash: Mapped[str] = mapped_column(Text)
    distance_source: Mapped[str] = mapped_column(Text)  # road_cache | estimate
    solver: Mapped[str] = mapped_column(Text)  # ortools | fallback
    stopped_by: Mapped[str] = mapped_column(Text)
    solve_ms: Mapped[int] = mapped_column(Integer)
    model_version: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(TsTz)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()


class VanRoute(Base):
    __tablename__ = "van_routes"
    __table_args__ = (Index("ix_van_routes_plan", "plan_id"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    plan_id: Mapped[int] = mapped_column(BigIntPK,
                                         ForeignKey("van_plans.id", ondelete="CASCADE"))
    vehicle_no: Mapped[int] = mapped_column(SmallInteger)
    km: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    minutes: Mapped[Decimal] = mapped_column(Numeric(10, 1))
    cash_load: Mapped[Decimal] = mapped_column(Money)
    cost_bdt: Mapped[Decimal] = mapped_column(Money)
    # Per leg (depot -> stops -> depot): km, minutes, source (road_cache | estimate), cache keys.
    legs: Mapped[list[dict[str, Any]]] = mapped_column(JsonDoc, default=list)


class VanStop(Base):
    __tablename__ = "van_stops"
    __table_args__ = (
        CheckConstraint(_in("status", STOP_STATUSES), name="ck_van_stops_status"),
        Index("ix_van_stops_plan", "plan_id"),
        Index("ix_van_stops_agent", "agent_id"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    plan_id: Mapped[int] = mapped_column(BigIntPK,
                                         ForeignKey("van_plans.id", ondelete="CASCADE"))
    route_id: Mapped[int | None] = mapped_column(
        BigIntPK,
        ForeignKey("van_routes.id", ondelete="CASCADE"))
    seq: Mapped[int | None] = mapped_column(SmallInteger)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    recommendation_id: Mapped[int | None] = mapped_column(BigInteger)  # source, no FK (rewritten)
    amount: Mapped[Decimal] = mapped_column(Money)
    eta_lo: Mapped[datetime | None] = mapped_column(TsTz)
    eta_hi: Mapped[datetime | None] = mapped_column(TsTz)
    deadline: Mapped[datetime | None] = mapped_column(TsTz)
    penalty_bdt: Mapped[Decimal] = mapped_column(Money)  # late penalty, or skip penalty if dropped
    source_quantile: Mapped[str] = mapped_column(Text)
    stockout_before_arrival_p: Mapped[Decimal | None] = mapped_column(Ratio)  # V3
    status: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JsonDoc, default=dict)
    delivered_at: Mapped[datetime | None] = mapped_column(TsTz)
    delivered_amount: Mapped[Decimal | None] = mapped_column(Money)
