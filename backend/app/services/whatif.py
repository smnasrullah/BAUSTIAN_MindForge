"""What-if (F8): re-project one float from the cached quantile paths with balance + delta.

Same seed, Monte Carlo config and stockout method as the risk cache, so `before` reproduces the
cached numbers (joint method: both floats move; the slider changes one float's balance).
"""

import hashlib
import threading
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Agent, FloatSnapshot
from app.models.enums import FloatType
from app.rules.risk_rules import HEADLINE_HORIZON, HORIZONS, RiskConfig, level_confidence, level_for
from app.schemas.risk import HorizonRisk
from app.schemas.whatif import BalancePoint, WhatIfIn, WhatIfOut, WhatIfScenario
from app.services import forecast, risk
from app.services.model_registry import active_model
from ml.inference import whatif
from ml.inference.stockout import StockoutConfig
from ml.inference.stockout_joint import Dependence, load_dependence
from ml.registry import FORECAST_MODEL

# Sampling 2,000 demand paths is most of a what-if call and does not depend on the slider, so
# each worker keeps the last few agents' paths (~2.3 MB each). The key holds a digest of the
# cached quantiles and the balance, so a new forecast or snapshot is a new entry.
_PATHS_MAX = 8
_paths: OrderedDict[tuple[object, ...], whatif.Paths | whatif.JointPaths] = OrderedDict()
_paths_lock = threading.Lock()
_dependence: dict[str, tuple[str, dict[str, Dependence] | None]] = {}


def _table(version: str) -> dict[str, Dependence] | None:
    """The served model's dependence table, read once per model version and worker."""
    directory = str(get_settings().artifacts_dir)
    hit = _dependence.get(directory)
    if hit is None or hit[0] != version:
        hit = (version, load_dependence(get_settings().artifacts_dir))
        _dependence[directory] = hit
    return hit[1]


def _remember(key: tuple[object, ...], make: Callable[[], whatif.Paths | whatif.JointPaths]
              ) -> whatif.Paths | whatif.JointPaths:
    with _paths_lock:
        hit = _paths.get(key)
        if hit is not None:
            _paths.move_to_end(key)
            return hit
    prepared = make()
    with _paths_lock:
        _paths[key] = prepared
        while len(_paths) > _PATHS_MAX:
            _paths.popitem(last=False)
    return prepared


def _digest(*arrays: np.ndarray) -> str:
    return hashlib.blake2b(b"".join(a.tobytes() for a in arrays), digest_size=16).hexdigest()


class WhatIfError(Exception):
    """delta_out_of_bounds (422)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _scenario(s: whatif.Scenario, now: datetime, cfg: RiskConfig) -> WhatIfScenario:
    res = s.result
    horizons: list[HorizonRisk] = []
    for h in HORIZONS:
        p = round(res.prob_within(h), 4)
        horizons.append(HorizonRisk(horizon_h=h, probability=p, level=level_for(p, h, cfg),
                                    confidence=round(level_confidence(p), 4)))
    return WhatIfScenario(
        balance=round(s.balance, 2),
        stockout_at=None if res.hours is None else now + timedelta(hours=res.hours),
        hours_to_stockout=None if res.hours is None else round(res.hours, 2),
        confidence=round(res.confidence, 4),
        level=next(r.level for r in horizons if r.horizon_h == HEADLINE_HORIZON),
        horizons=horizons,
        series=[BalancePoint(ts=now + timedelta(hours=h), hour=h, low=round(float(lo), 2),
                             expected=round(float(mid), 2), high=round(float(hi), 2))
                for h, (lo, mid, hi) in enumerate(s.bands)],
    )


def run(session: Session, agent: Agent, req: WhatIfIn, cfg: RiskConfig, seed: int
        ) -> WhatIfOut | None:
    """None when the forecast cache or the as-of balance is missing (not ready)."""
    mv = active_model(session, FORECAST_MODEL)
    if mv is None:
        return None
    now = forecast.sim_now(session)
    snap = session.scalar(select(FloatSnapshot).where(FloatSnapshot.agent_id == agent.id,
                                                      FloatSnapshot.ts == now))
    quantiles = risk.load_quantiles(session, mv.id, max(HORIZONS), agent.id)
    ft = req.float_type
    drain, inflow = quantiles.get((agent.id, ft)), quantiles.get((agent.id, risk.INFLOW_OF[ft]))
    if snap is None or drain is None or inflow is None:
        return None
    cash0, em0 = float(snap.cash_balance), float(snap.emoney_balance)
    b0 = cash0 if ft == FloatType.cash else em0
    capacity = float(agent.cash_capacity if ft == FloatType.cash else agent.emoney_capacity)
    # A float may sit above its nominal capacity; it can then only be drawn down.
    if not 0 <= b0 + req.delta_amount <= max(capacity, b0):
        raise WhatIfError("delta_out_of_bounds")
    mc = StockoutConfig()
    if get_settings().stockout_method == "joint":
        # Same joint paths as the risk cache: cash-out drains cash, cash-in drains e-money.
        out_q, in_q = quantiles[(agent.id, FloatType.cash)], quantiles[(agent.id, FloatType.emoney)]
        dep = risk.dependence_for(_table(mv.version), agent)
        joint = _remember(
            ("joint", seed, agent.id, ft, cash0, em0, _digest(out_q, in_q), dep, mc),
            lambda: whatif.prepare_joint(cash0, em0, ft == FloatType.cash, out_q, in_q, mc, dep,
                                         risk.joint_rng(seed, agent.id)))
        assert isinstance(joint, whatif.JointPaths)
        before, after = joint.before, whatif.after_joint(joint, req.delta_amount, mc)
    else:
        single = _remember(
            ("single", seed, agent.id, ft, b0, _digest(drain, inflow), mc),
            lambda: whatif.prepare(b0, drain, inflow, mc, risk.path_rng(seed, agent.id, ft)))
        assert isinstance(single, whatif.Paths)
        before, after = single.before, whatif.after(single, req.delta_amount, mc)
    return WhatIfOut(
        agent_id=agent.id, float_type=ft, delta_amount=req.delta_amount, capacity=capacity,
        as_of=now, before=_scenario(before, now, cfg), after=_scenario(after, now, cfg),
        model_version=mv.version, generated_at=datetime.now(UTC),
    )
