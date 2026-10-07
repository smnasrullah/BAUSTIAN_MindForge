"""Plan a demo story at an anchor hour (live_story.py explains the story).

The top-up is solved backwards on the story agent's expected demand (whole BDT, the same values
the engine will use), so the forward simulation reproduces the path exactly: cash stays above
zero until the stock-out hour and runs dry STOCKOUT_LOCAL.minute minutes into it.
"""

import logging
from datetime import datetime, timedelta

import numpy as np

from ml.data_gen import demo_spec
from ml.data_gen import live_calendar as lc
from ml.data_gen.live import H1, Engine, LiveWorld, local
from ml.data_gen.live_story import (
    ANOMALY_AFTER_H,
    FRESH_ANOMALY_DAYS,
    REANCHOR_ANOMALY_H,
    STORY_DISTRICT,
    Story,
    candidates,
)
from ml.data_gen.timeline import BDT, midnight

log = logging.getLogger(__name__)
ANOMALY_GAP = timedelta(days=21)


def _calendar_explains(day: datetime, holidays: tuple[lc.Holiday, ...]) -> bool:
    """A real salary day, factory wage day or pre-Eid rush already explains a cash-out rush."""
    d = day.date()
    wage = d.day in lc.cal.GARMENT_DAYS and STORY_DISTRICT in lc.cal.GARMENT_DISTRICTS
    return d.day <= 3 or wage or lc.eid_offset(d, holidays) is not None


def _path(engine: Engine, anchor: datetime, stockout: datetime
          ) -> tuple[float, float, float] | None:
    """(top-up cash, min cash, min e-money slack) on the expected path, or None if infeasible."""
    i = engine.story_i
    if i is None:
        return None
    t_c = stockout.replace(minute=0)
    hours = int((t_c - anchor) / H1)
    d_in, d_out = np.zeros(hours + 1), np.zeros(hours + 1)
    for k in range(hours + 1):
        lt = local(anchor + k * H1)
        blk = engine.block(lt.date())  # the story already sets expected demand in the block
        d_in[k], d_out[k] = blk.amt_in[i, lt.hour], blk.amt_out[i, lt.hour]
    if d_out[-1] <= d_in[-1]:
        return None
    frac = stockout.minute / 60
    cash = np.zeros(hours + 1)
    cash[-1] = round(frac * (d_out[-1] - d_in[-1]))
    for k in range(hours - 1, -1, -1):
        cash[k] = cash[k + 1] - d_in[k] + d_out[k]
    em = np.zeros(hours + 1)
    em[0] = engine.em_target[i]
    for k in range(hours):
        em[k + 1] = em[k] - d_in[k] + d_out[k]
    slack = float((em - d_in).min())  # e-money must cover every hour's cash-in
    if cash.min() <= 0 or cash[0] > 0.95 * engine.cash_cap[i] or slack < 0:
        return None
    return float(cash[0]), float(cash.min()), slack


def plan(world: LiveWorld, anchor: datetime, fresh: bool) -> Story | None:
    """The first feasible story at `anchor` (a UTC hour), or None (logged).

    fresh: the anchor is the end of a newly generated window, so the anomaly can start days
    before it and the anchor day can be kept dry; otherwise only the future is shaped."""
    if not any(a.code == demo_spec.STOCKOUT_AGENT for a in world.agents):
        return None
    for stockout in candidates(anchor):
        day = stockout.astimezone(BDT)
        if not fresh and day.date() == local(anchor).date():
            continue  # today's earlier hours are already written; shape only later days
        wage_day = None if _calendar_explains(day, world.holidays) else day.date()
        dry = (day.date(),) if not fresh else tuple(sorted({local(anchor).date(), day.date()}))
        if fresh:
            a0 = midnight(local(anchor).date() - timedelta(days=FRESH_ANOMALY_DAYS))
            a1 = anchor + ANOMALY_AFTER_H * H1
        elif all(anchor - s.anomaly_end >= ANOMALY_GAP for s in world.stories):
            a0, a1 = anchor, anchor + REANCHOR_ANOMALY_H * H1
        else:  # an episode every day would become the agent's normal: keep them apart
            a0 = a1 = anchor
        probe = Story(anchor, stockout, 0.0, a0, a1, wage_day, dry)
        engine = Engine(world.with_stories((*world.stories, probe)))
        found = _path(engine, anchor, stockout)
        if found is None:
            continue
        top_up, low, _slack = found
        log.info("demo story: top-up %.0f at %s, stock-out %s (min cash %.0f, wage event %s)",
                 top_up, local(anchor).isoformat(), day.isoformat(), low, wage_day)
        return Story(anchor, stockout, top_up, a0, a1, wage_day, dry)
    log.warning("demo story: no feasible stock-out after %s; story skipped", anchor.isoformat())
    return None
