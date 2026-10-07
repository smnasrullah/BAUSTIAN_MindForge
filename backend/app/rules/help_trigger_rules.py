"""Automatic liquidity help: when to ask, how much, by when, and who to ask first.

Pure functions, no database. The trigger service (app/services/help_trigger.py) feeds these
the forecast and balances and writes the result. Nothing here moves money.

Trigger (business rule, separate from the ML model): the projected balance on the high-demand
line (drain at P90, inflow at P10) drops below the agent's safety buffer within the next N hours,
the headline risk is red, and the projection falls short of the buffer by at least the minimum
shortfall. Amount = projected shortfall to zero + buffer, rounded up to ROUND_BDT, capped.
The buffer is a share of the agent's own average daily demand, not one number for everyone.
"""

import math
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

import numpy as np

from app.models.enums import RiskLevelCode
from app.rules.rebalance_rules import ROUND_BDT, Need, RebalanceConfig, assess

DAY_HOURS = 24
# Default deadline floor (TriggerPolicy.deadline_floor_min): never ask by a time already past.
MIN_DEADLINE = timedelta(minutes=15)
ASK_WINDOW = timedelta(days=7)  # asks counted for the fairness rotation
ASK_PENALTY_KM = 1.0  # each ask in the window counts as this much extra distance
RESPONSE_WEIGHT_KM = 2.0  # a helper who usually says yes ranks as if this much closer


@dataclass(frozen=True)
class TriggerPolicy:
    """Admin-controlled trigger settings. Defaults: app/core/config.py (HELP_TRIGGER_*)."""

    horizon_h: int = 6  # N: look this far ahead
    buffer_pct: float = 25.0  # safety buffer, percent of the agent's average daily demand
    min_shortfall_bdt: float = 5_000.0  # ignore projections that miss the buffer by less
    max_request_bdt: float = 200_000.0  # cap on one request
    lead_margin_h: float = 1.0  # needed_by = time to stock-out minus this
    radius_km: float = 5.0  # helpers must sit this close
    wave_timeout_min: int = 15  # wave N+1 goes out when wave N has had this long
    max_waves: int = 3
    recent_ask_h: float = 2.0  # a helper asked this recently is left out
    deadline_floor_min: int = 15  # needed_by is at least this far ahead
    urgent_wave_multiplier: float = 2.0  # urgent: wave 1 asks this many times more agents
    max_new_per_tick: int = 3  # new requests per run, most urgent first; the rest wait

    def __post_init__(self) -> None:
        if not 1 <= self.deadline_floor_min <= 240:
            raise ValueError("deadline floor must be 1..240 min")
        if not 1 <= self.urgent_wave_multiplier <= 5:
            raise ValueError("urgent wave multiplier must be 1..5")
        if not 1 <= self.max_new_per_tick <= 100:
            raise ValueError("new requests per tick must be 1..100")
        if not 1 <= self.horizon_h <= 72:
            raise ValueError("trigger horizon must be 1..72 h")
        if not 0 <= self.buffer_pct <= 100:
            raise ValueError("buffer percentage must be 0..100")
        if self.min_shortfall_bdt < 0 or self.max_request_bdt < ROUND_BDT:
            raise ValueError("minimum shortfall >= 0 and maximum request >= one rounding step")
        if self.lead_margin_h < 0 or self.radius_km <= 0 or self.recent_ask_h < 0:
            raise ValueError("lead margin and recent-ask window >= 0, radius > 0")
        if self.wave_timeout_min < 1 or not 1 <= self.max_waves <= 10:
            raise ValueError("wave timeout >= 1 min, 1..10 waves")


@dataclass(frozen=True)
class Verdict:
    fires: bool
    reason: str  # ok | risk_not_red | above_buffer | below_min_shortfall
    projected_low_bdt: float  # lowest projected balance inside the horizon (pessimistic path)
    buffer_bdt: float
    amount_bdt: float  # 0 unless fires
    stockout_h: float  # hours until the pessimistic path or the median projection runs out


def round_up(value: float) -> float:
    return float(math.ceil(value / ROUND_BDT) * ROUND_BDT) if value > 0 else 0.0


def buffer_bdt(avg_daily_demand: float, policy: TriggerPolicy) -> float:
    """The agent's own safety buffer: a percentage of what it usually drains in a day."""
    return round_up(policy.buffer_pct / 100 * avg_daily_demand)


def _need(balance: float, drain_high: np.ndarray, inflow_low: np.ndarray, buffer: float,
          policy: TriggerPolicy) -> Need:
    cfg = RebalanceConfig(horizon_h=policy.horizon_h)
    return replace(assess(balance, 0.0, drain_high, inflow_low, cfg), buffer=buffer)


def evaluate(balance: float, drain_high: np.ndarray, inflow_low: np.ndarray, buffer: float,
             level: RiskLevelCode | None, median_stockout_h: float | None,
             policy: TriggerPolicy) -> Verdict:
    """Decide for one agent and one float. drain_high / inflow_low: hourly BDT, >= N hours."""
    need = _need(balance, drain_high, inflow_low, buffer, policy)
    low = balance - need.peak_drain
    hours = [h for h in (need.crossing_h, median_stockout_h) if h is not None]
    stockout_h = min(hours) if hours else float(policy.horizon_h)
    base = Verdict(fires=False, reason="ok", projected_low_bdt=round(low, 2), buffer_bdt=buffer,
                   amount_bdt=0.0, stockout_h=stockout_h)
    if level != RiskLevelCode.red:
        return replace(base, reason="risk_not_red")
    if low >= buffer:
        return replace(base, reason="above_buffer")
    if buffer - low < policy.min_shortfall_bdt:
        return replace(base, reason="below_min_shortfall")
    wanted = round_up(need.shortfall + buffer)
    amount = min(wanted, math.floor(policy.max_request_bdt / ROUND_BDT) * ROUND_BDT)
    return replace(base, fires=True, amount_bdt=amount)


def deadline_after(stockout_h: float, policy: TriggerPolicy) -> timedelta:
    """needed_by = time to stock-out minus the lead margin, never sooner than the floor."""
    floor = timedelta(minutes=policy.deadline_floor_min)
    return max(floor, timedelta(hours=stockout_h - policy.lead_margin_h))


def deadline_after_stockout(stockout_h: float, policy: TriggerPolicy) -> bool:
    """The floor pushed needed_by past the forecast stock-out: ask "as soon as possible"."""
    return deadline_after(stockout_h, policy) > timedelta(hours=max(stockout_h, 0.0))


def is_urgent(stockout_h: float, policy: TriggerPolicy) -> bool:
    """Stock-out is forecast sooner than twice the deadline floor."""
    return timedelta(hours=stockout_h) < 2 * timedelta(minutes=policy.deadline_floor_min)


def wave_one_agents(per_wave: int, urgent: bool, policy: TriggerPolicy) -> int:
    """How many agents wave 1 asks: the normal wave size, larger when urgent."""
    return math.ceil(per_wave * policy.urgent_wave_multiplier) if urgent else per_wave


def surplus_bdt(balance: float, drain_high: np.ndarray, inflow_low: np.ndarray, buffer: float,
                policy: TriggerPolicy) -> float:
    """What a helper can give away and still keep its own need plus its own buffer."""
    return _need(balance, drain_high, inflow_low, buffer, policy).surplus


def asked_recently(last_asked: datetime | None, now: datetime, policy: TriggerPolicy) -> bool:
    return last_asked is not None and now - last_asked < timedelta(hours=policy.recent_ask_h)


@dataclass(frozen=True)
class Helper:
    user_id: uuid.UUID
    distance_km: float
    surplus: float
    asks_in_window: int
    asked: int
    accepted: int


def response_rate(accepted: int, asked: int) -> float:
    """Smoothed: a helper with no history starts at one half, not at zero or one."""
    return (accepted + 1) / (asked + 2)


def rank_score(h: Helper) -> float:
    """Lower is asked first: nearby, rarely asked lately, usually says yes."""
    return (h.distance_km + ASK_PENALTY_KM * h.asks_in_window
            - RESPONSE_WEIGHT_KM * response_rate(h.accepted, h.asked))


def rank(helpers: list[Helper]) -> list[Helper]:
    """Deterministic order: score, then more surplus, then user id (stable across runs)."""
    return sorted(helpers, key=lambda h: (rank_score(h), -h.surplus, str(h.user_id)))


def learned_wave_size(probs: list[float], cap: int, target: float) -> int:
    """Wave size from model chances (best first): the fewest helpers whose chance that at least
    one says yes reaches `target`. A rule, not the model: never more than `cap` (the rule's
    wave size), never fewer than one, and only over helpers the rules already allow."""
    if cap < 1 or not probs:
        return 0
    miss = 1.0
    for k, p in enumerate(probs[:cap], start=1):
        miss *= 1.0 - min(max(p, 0.0), 1.0)
        if 1.0 - miss >= target:
            return k
    return min(cap, len(probs))
