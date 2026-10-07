"""Anomaly cache: every agent's last 7 days before the forecast origin (data clock) scored by
its peer group's forest.

Only flagged windows are stored, with their peer evidence. Re-running replaces open flags;
reviewed ones (confirmed / dismissed) stay with their audit trail and are not re-flagged.
"""

import logging
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core import clock
from app.models import Anomaly, SystemMeta
from app.models.enums import AnomalyStatus
from app.services import forecast, notify
from app.services.model_registry import register_anomaly_model
from ml.explain.anomaly_evidence import evidence
from ml.features.anomaly import HISTORY_H, WINDOW_H, load_series, window_features
from ml.inference.anomaly import load_detector

log = logging.getLogger(__name__)
CACHE_KEY = "anomaly_cache"
METHOD = "iforest-peer-window-1"


def _utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)


def precompute(session: Session, artifacts_dir: Path, force: bool = False) -> int:
    """Score all agents at the origin; returns flags written (0 when the cache is current)."""
    mv = register_anomaly_model(session, artifacts_dir)
    now = forecast.sim_now(session)
    data = session.get(SystemMeta, "data_version")
    key = {"model_version": mv.version, "sim_now": now.isoformat(), "method": METHOD,
           "data_version": data.value if data else None}
    meta = session.get(SystemMeta, CACHE_KEY)
    if not force and meta is not None and meta.value == key:
        log.info("anomaly cache current (%s)", mv.version)
        return 0
    detector = load_detector(artifacts_dir)
    win = clock.window_at(now)
    end = win.hour_index(now)
    # Live ticks read only what the score uses: the window, its history and one leading hour.
    since = end - WINDOW_H - HISTORY_H - 1 if clock.is_live() else 0
    series = load_series(session, end, win, since)
    w = window_features(series, end, detector.spec)
    groups = np.array(series.groups)
    score, threshold = detector.score(w.x, groups)
    start_ts, end_ts = win.ts_of(end - WINDOW_H), win.ts_of(end)
    # Agents with an open flag were notified then; only new flags notify. (The live window moves
    # every hour, so "the same flag" means the same agent, not the same window start.)
    known = set(session.scalars(select(Anomaly.agent_id).where(
        Anomaly.status == AnomalyStatus.open)))
    session.execute(delete(Anomaly).where(Anomaly.status == AnomalyStatus.open))
    # A human already reviewed a window that overlaps this one: keep their decision.
    reviewed = {a for a, ts in session.execute(select(Anomaly.agent_id, Anomaly.window_end))
                if _utc(ts) > start_ts}
    flags: list[Anomaly] = []
    for i in np.flatnonzero(score > threshold):
        agent_id = int(series.agent_ids[i])
        if agent_id in reviewed:
            continue
        flags.append(Anomaly(model_version_id=mv.id, agent_id=agent_id, window_start=start_ts,
                             window_end=end_ts, score=round(float(score[i]), 4),
                             features=evidence(w, score, threshold, groups, int(i)) | {
                                 "as_of": now.isoformat()}))
    session.add_all(flags)
    session.merge(SystemMeta(key=CACHE_KEY, value=key))
    session.flush()
    notify.anomalies_new(session, [f for f in flags if f.agent_id not in known])
    written = len(flags)
    log.info("anomaly cache: %d of %d agents flagged at %s (%s)", written,
             len(series.agent_ids), now.isoformat(), mv.version)
    return written
