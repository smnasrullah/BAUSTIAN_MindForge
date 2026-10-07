"""Split swap matching (S1): min-cost flow as a MILP inside the swap rules."""

from app.models.enums import FloatType
from app.rules.swap_rules import Donor, FlowConfig, Receiver, SwapConfig, match, match_flow

CFG = SwapConfig(radius_km=5.0, min_amount_bdt=5_000.0)
CASH = FloatType.cash


def _donor(aid: int, surplus: float, dlat: float = 0.0, dist: int = 1) -> Donor:
    return Donor(aid, dist, 23.80 + dlat, 90.40, {CASH: surplus})


def _recv(aid: int, need: float, dlat: float = 0.0, dist: int = 1) -> Receiver:
    return Receiver(aid, dist, 23.80 + dlat, 90.40, CASH, need)


def test_one_shortage_is_split_over_donors_the_assignment_cannot_combine() -> None:
    donors = [_donor(1, 30_000), _donor(2, 25_000, 0.005)]
    receivers = [_recv(9, 50_000, 0.002)]
    one = match(donors, receivers, CFG)
    assert len(one) == 1 and not one[0].van_trip_saved  # 30,000 of 50,000
    split = match_flow(donors, receivers, CFG, FlowConfig())
    assert sum(m.amount for m in split) == 50_000
    assert all(m.van_trip_saved for m in split) and len(split) == 2
    assert all(m.amount >= CFG.min_amount_bdt for m in split)


def test_fairness_cap_limits_how_many_agents_one_donor_helps() -> None:
    donors = [_donor(1, 100_000)]
    receivers = [_recv(10 + k, 10_000, 0.001 * k) for k in range(4)]
    for cap in (1, 2, 3):
        found = match_flow(donors, receivers, CFG, FlowConfig(max_receivers_per_donor=cap))
        assert len({m.receiver.agent_id for m in found}) == cap
    many = match_flow([_donor(k, 20_000, 0.001 * k) for k in range(1, 6)],
                      [_recv(50, 100_000)], CFG, FlowConfig(max_donors_per_receiver=2))
    assert len(many) == 2 and sum(m.amount for m in many) == 40_000


def test_travel_time_window_and_rules_are_kept() -> None:
    donors = [_donor(1, 50_000, 0.03), _donor(2, 50_000, 0.002)]  # ~3.3 km and ~0.2 km away
    receivers = [_recv(9, 20_000)]
    found = match_flow(donors, receivers, CFG, FlowConfig(speed_kmh=15.0), {9: 0.1})
    assert [m.donor.agent_id for m in found] == [2]  # 3.3 km takes 13 min > 6 min left
    assert match_flow([_donor(1, 50_000, dist=2)], receivers, CFG, FlowConfig()) == []
    assert match_flow([_donor(1, 50_000, 0.1)], receivers, CFG, FlowConfig()) == []  # > 5 km
    assert match_flow([_donor(1, 4_000)], receivers, CFG, FlowConfig()) == []  # < minimum


def test_pinned_receivers_are_served_first() -> None:
    donors = [_donor(1, 20_000)]
    receivers = [_recv(9, 20_000, 0.01), _recv(8, 20_000)]  # 8 is nearer
    plain = match_flow(donors, receivers, CFG, FlowConfig(max_receivers_per_donor=1))
    pinned = match_flow(donors, receivers, CFG, FlowConfig(max_receivers_per_donor=1),
                        first=frozenset({9}))
    assert [m.receiver.agent_id for m in plain] == [8]
    assert [m.receiver.agent_id for m in pinned] == [9]
