"""S4 realism sensitivity: failed / late physical deliveries and the full action costs."""

from datetime import timedelta

import numpy as np

from app.models.enums import FloatType
from app.models.enums import RecommendationChannel as Channel
from app.rules.channel_rules import ChannelConfig
from app.rules.impact_rules import ImpactConfig
from app.rules.rebalance_rules import Advice, RebalanceConfig
from app.rules.swap_rules import SwapConfig
from app.services.impact_policies import AiPolicy, _Order
from app.services.impact_realism import Costs, Realism, Unreliable, action_cost, summary
from app.services.impact_sim import Delivery, run
from tests.test_impact_sim import START, _world


class _OneVan:
    """Orders one 40,000 BDT cash van at hour 0, landing at hour 12 (08:00)."""

    def __init__(self, channel: Channel = Channel.van) -> None:
        self.channel = channel

    def decide(self, t: int, cash: np.ndarray, em: np.ndarray, pending: np.ndarray
               ) -> list[Delivery]:
        if t != 0:
            return []
        return [Delivery(0, 12, 0, FloatType.cash, 40_000.0, self.channel, "V0")]


def test_failed_delivery_lands_nothing_and_late_one_lands_later() -> None:
    w = _world([0.0], [100_000.0], [True])
    ok = run(w, _OneVan())
    fail = run(w, Unreliable(_OneVan(), Realism(p_fail=1.0, p_delay=0.0)))
    late = run(w, Unreliable(_OneVan(), Realism(p_fail=0.0, p_delay=1.0, delay_h=3)))
    lost = [float(o.unmet_out.sum()) for o in (ok, late, fail)]
    assert lost[0] <= lost[1] < lost[2]  # never landing is worst
    first_short = [int(np.argmax(o.unmet_out[0] > 0.5)) for o in (ok, late)]
    assert first_short == [16, 12]  # on time it lasts to 12:00; late, customers wait at 08:00
    assert fail.deliveries[0].failed and late.deliveries[0].arrive == 15
    assert summary(w, fail, 0.5)["failed"] == 1
    digital = run(w, Unreliable(_OneVan(Channel.top_up), Realism(p_fail=1.0)))
    assert not digital.deliveries[0].failed  # top-ups are not physical


def test_action_cost_counts_every_channel() -> None:
    w = _world([0.0, 0.0], [100_000.0, 100_000.0], [True, True])
    o = run(w, _OneVan())
    o.deliveries += [Delivery(1, 2, 1, FloatType.emoney, 10_000.0, Channel.top_up),
                     Delivery(1, 3, 1, FloatType.cash, 5_000.0, Channel.urgent_manual, "U1"),
                     Delivery(1, 3, 1, FloatType.cash, 5_000.0, Channel.swap, donor=0)]
    c = action_cost(w, o, Costs(1_500, 2_500, 0.5, 10))
    assert c["van_bdt"] == 1_500 and c["urgent_bdt"] == 2_500
    assert c["topup_fee_bdt"] == 50.0 and 0 < c["travel_bdt"] < 2  # 0.1 km hand-over
    assert c["total_bdt"] == round(1_500 + 2_500 + 50 + c["travel_bdt"], 2)


def test_agent_short_of_both_floats_is_one_cash_swap_receiver() -> None:
    """Regression: the e-money order of an agent must not enter matching as a second cash
    need (the first version did, and the last match silently won)."""
    w = _world([0.0, 90_000.0], [0.0, 90_000.0], [True, False])
    pol = AiPolicy(w, {}, ImpactConfig(), RebalanceConfig(), SwapConfig(), ChannelConfig())
    later = START + timedelta(hours=10)
    orders = [_Order(0, FloatType.cash, Advice(20_000.0, later, later, False, False)),
              _Order(0, FloatType.emoney, Advice(35_000.0, later, later, False, False))]
    found = pol._swaps(orders, {1: {FloatType.cash: 80_000.0}}, START)
    assert list(found) == [0] and [m.amount for m in found[0]] == [20_000.0]
