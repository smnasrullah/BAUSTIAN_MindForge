"""Van plan API fixture data: the rebalance test market plus four Dhaka agents short of cash.

AGT-0001 (Dhaka) is covered by the market's pending swap -> listed as swap_suggested.
AGT-0002 (Chattogram) is short too but belongs to another distributor -> never in a Dhaka plan.
"""

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.models import (
    Agent,
    Distributor,
    FloatSnapshot,
    Forecast,
    ModelVersion,
    Recommendation,
    StockoutPrediction,
)
from app.models.enums import (
    FloatType,
    RecommendationChannel,
    RecommendationKind,
    UrbanRural,
)
from tests.rebalance_helpers import NOW, _flat, build_market

# code -> (lat, lng, amount, hours to stockout, cash-out per hour)
SHORT = {"AGT-9101": (23.7465, 90.3760, 60_000, 3.0, 4_000),
         "AGT-9102": (23.7806, 90.4070, 80_000, 5.0, 3_000),
         "AGT-9103": (23.8223, 90.4265, 50_000, 7.0, 2_500),
         "AGT-9104": (23.7104, 90.4074, 70_000, 2.0, 5_000)}


def build_van_market() -> None:
    build_market()
    with Session(get_engine()) as session, session.begin():
        dhk = session.scalar(select(Distributor.id).where(Distributor.code == "DST-DHK"))
        mv = session.scalar(select(ModelVersion.id).where(ModelVersion.version == "test-flat"))
        assert dhk is not None and mv is not None
        for code, (lat, lng, amount, hours, out) in SHORT.items():
            agent = Agent(code=code, name=f"Van test {code[-2:]}", distributor_id=dhk,
                          region="Dhaka", district="Dhaka", upazila="Dhanmondi",
                          urban_rural=UrbanRural.urban, tier=2, lat=lat, lng=lng,
                          cash_capacity=Decimal("150000"), emoney_capacity=Decimal("150000"))
            session.add(agent)
            session.flush()
            session.execute(insert(Forecast), _flat(mv, agent.id, out, 0))
            stockout = NOW + timedelta(hours=hours)
            session.add(Recommendation(
                agent_id=agent.id, model_version_id=mv, kind=RecommendationKind.add_cash,
                float_type=FloatType.cash, amount_bdt=Decimal(amount),
                deadline_at=stockout - timedelta(hours=3), channel=RecommendationChannel.van,
                rationale={"stockout_at": stockout.isoformat(), "risk_level": "red"}))


AMBER = "AGT-9105"  # amber: the median path (q50) needs 67,000 (52,000 short + 15,000 buffer)
STEEP = "AGT-9101"  # stockout curve: P = 0.5 now, 0.95 from hour 1 -> deadline 0 h, flagged


def add_amber_and_curve() -> None:
    """After build_van_market: one amber agent (balance 20,000, 3,000/h out, nothing in; its
    recommendation says 90,000) and a steep stockout curve for AGT-9101."""
    with Session(get_engine()) as session, session.begin():
        dhk = session.scalar(select(Distributor.id).where(Distributor.code == "DST-DHK"))
        mv = session.scalar(select(ModelVersion.id).where(ModelVersion.version == "test-flat"))
        assert dhk is not None and mv is not None
        agent = Agent(code=AMBER, name="Van test 05", distributor_id=dhk, region="Dhaka",
                      district="Dhaka", upazila="Dhanmondi", urban_rural=UrbanRural.urban,
                      tier=2, lat=23.7550, lng=90.3900, cash_capacity=Decimal("150000"),
                      emoney_capacity=Decimal("150000"))
        session.add(agent)
        session.flush()
        session.add(FloatSnapshot(agent_id=agent.id, ts=NOW, cash_balance=Decimal(20_000),
                                  emoney_balance=Decimal(50_000)))
        session.execute(insert(Forecast), _flat(mv, agent.id, 3_000, 0))
        stockout = NOW + timedelta(hours=6)
        session.add(Recommendation(
            agent_id=agent.id, model_version_id=mv, kind=RecommendationKind.add_cash,
            float_type=FloatType.cash, amount_bdt=Decimal(90_000),
            deadline_at=stockout - timedelta(hours=3), channel=RecommendationChannel.van,
            rationale={"stockout_at": stockout.isoformat(), "risk_level": "amber"}))
        steep = session.scalar(select(Agent.id).where(Agent.code == STEEP))
        session.add(StockoutPrediction(
            model_version_id=mv, agent_id=steep, float_type=FloatType.cash, ts=NOW,
            stockout_at=NOW + timedelta(hours=1), hours_to_stockout=Decimal(1),
            confidence=Decimal("0.9"), prob_by_hour=[0.5] + [0.95] * 72, generated_at=NOW))
