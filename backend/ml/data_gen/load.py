"""Write a Dataset to the database (COPY on Postgres, batched INSERT elsewhere).

Full load replaces all time series, events and weather. `only_agents` rewrites just those
agents' rows (used by the demo_scenario CLI). Agents and distributors are upserted by code.
"""

from collections.abc import Iterable, Iterator
from decimal import Decimal
from typing import Any

import numpy as np
from sqlalchemy import Table, delete, insert, select
from sqlalchemy.orm import Session

from app.core.config import DATA_VERSION
from app.models import Agent, Distributor
from app.models.system_meta import SystemMeta
from app.models.timeseries import Event, FloatSnapshot, Transaction, WeatherDaily
from app.services.seed import DISTRIBUTORS
from ml.data_gen.agents import AgentSpec
from ml.data_gen.dataset import Dataset
from ml.data_gen.timeline import END, HOLDOUT_START, SIM_NOW, START, holdout_mask, utc_hours

BATCH = 20_000
SNAPSHOT_COLS = ("agent_id", "ts", "cash_balance", "emoney_balance", "is_holdout")
TXN_COLS = ("agent_id", "ts", "txn_type", "amount_bdt", "txn_count", "is_holdout")


def _upsert_distributors(session: Session) -> dict[str, int]:
    existing = {d.code: d for d in session.scalars(select(Distributor))}
    for s in DISTRIBUTORS:
        if s.code not in existing:
            row = Distributor(code=s.code, name=s.name, region=s.region, district=s.district,
                              hub_lat=s.hub_lat, hub_lng=s.hub_lng)
            session.add(row)
            existing[s.code] = row
    session.flush()
    return {code: d.id for code, d in existing.items()}


def upsert_agents(session: Session, agents: Iterable[AgentSpec], codes: set[str]
                  ) -> dict[str, int]:
    """Distributors + the agents in `codes` (by code); returns code -> agents.id."""
    dist_ids = _upsert_distributors(session)
    existing = {a.code: a for a in session.scalars(select(Agent).where(Agent.code.in_(codes)))}
    for a in agents:
        if a.code not in codes:
            continue
        row = existing.get(a.code) or Agent(code=a.code)
        row.name, row.distributor_id = a.name, dist_ids[a.distributor_code]
        row.region, row.district, row.upazila = a.region, a.district, a.upazila
        row.urban_rural, row.tier, row.lat, row.lng = a.area, a.tier, a.lat, a.lng
        row.cash_capacity = Decimal(a.cash_capacity)
        row.emoney_capacity = Decimal(a.emoney_capacity)
        row.opened_on, row.is_active = a.opened_on, True
        if a.code not in existing:
            session.add(row)
            existing[a.code] = row
    session.flush()
    return {code: r.id for code, r in existing.items()}


def _snapshot_rows(ds: Dataset, ids: dict[str, int]) -> Iterator[tuple[Any, ...]]:
    ts, hold = utc_hours(), holdout_mask().tolist()
    cash = np.round(ds.floats.cash).astype(np.int64)
    em = np.round(ds.floats.emoney).astype(np.int64)
    for i, a in enumerate(ds.agents):
        if a.code in ids:
            aid, c, e = ids[a.code], cash[i].tolist(), em[i].tolist()
            for t in range(len(ts)):
                yield aid, ts[t], c[t], e[t], hold[t]


def _txn_rows(ds: Dataset, ids: dict[str, int]) -> Iterator[tuple[Any, ...]]:
    ts, hold = utc_hours(), holdout_mask().tolist()
    fl = ds.floats
    for kind, amt, cnt in (("cash_in", fl.served_in, fl.cnt_in),
                           ("cash_out", fl.served_out, fl.cnt_out)):
        rounded = np.round(amt).astype(np.int64)
        for i, a in enumerate(ds.agents):
            if a.code not in ids:
                continue
            aid = ids[a.code]
            for t in np.flatnonzero((rounded[i] > 0) & (cnt[i] > 0)).tolist():
                yield aid, ts[t], kind, int(rounded[i, t]), int(cnt[i, t]), hold[t]


def bulk(session: Session, table: Table, cols: tuple[str, ...],
         rows: Iterable[tuple[Any, ...]]) -> int:
    n = 0
    if session.get_bind().dialect.name == "postgresql":
        raw = session.connection().connection.driver_connection
        with raw.cursor() as cur, cur.copy(
            f"COPY {table.name} ({', '.join(cols)}) FROM STDIN"
        ) as cp:
            for row in rows:
                cp.write_row(row)
                n += 1
        return n
    batch: list[dict[str, Any]] = []
    for row in rows:
        batch.append(dict(zip(cols, row, strict=True)))
        if len(batch) >= BATCH:
            session.execute(insert(table), batch)
            n, batch = n + len(batch), []
    if batch:
        session.execute(insert(table), batch)
        n += len(batch)
    return n


def _set_meta(session: Session, key: str, value: Any) -> None:
    session.merge(SystemMeta(key=key, value=value))


def _write_meta(session: Session, ds: Dataset) -> None:
    _set_meta(session, "seed", ds.seed)
    _set_meta(session, "data_version", DATA_VERSION)
    _set_meta(session, "clock_mode", "fixed")
    _set_meta(session, "sim_now", SIM_NOW.isoformat())
    _set_meta(session, "data_range", {"start": START.isoformat(), "end": END.isoformat(),
                                      "holdout_start": HOLDOUT_START.isoformat()})
    _set_meta(session, "synthetic_labels", {
        "anomalies": [lab.as_json() for lab in ds.anomalies],
        "demo": ds.demo,
    })


def load(session: Session, ds: Dataset, only_agents: set[str] | None = None) -> dict[str, int]:
    """Write inside the caller's transaction; returns row counts written."""
    codes = only_agents if only_agents is not None else {a.code for a in ds.agents}
    ids = upsert_agents(session, ds.agents, codes)
    counts: dict[str, int] = {"agents": len(ids)}
    snap, txn = FloatSnapshot.__table__, Transaction.__table__
    if only_agents is None:
        for model in (Transaction, FloatSnapshot, Event, WeatherDaily):
            session.execute(delete(model))
        session.add_all(Event(type=e.type, name_en=e.name_en, name_bn=e.name_bn,
                              starts_at=e.starts_at, ends_at=e.ends_at, district=e.district,
                              intensity=Decimal(str(e.intensity))) for e in ds.events)
        session.add_all(
            WeatherDaily(district=w.district, date=w.date, rain_mm=Decimal(str(w.rain_mm)),
                         temp_c=Decimal(str(w.temp_c)), severe=w.severe)
            for w in ds.weather
        )
        session.flush()
        counts["events"], counts["weather_daily"] = len(ds.events), len(ds.weather)
    else:
        agent_ids = list(ids.values())
        session.execute(delete(Transaction).where(Transaction.agent_id.in_(agent_ids)))
        session.execute(delete(FloatSnapshot).where(FloatSnapshot.agent_id.in_(agent_ids)))
    counts["float_snapshots"] = bulk(session, snap, SNAPSHOT_COLS, _snapshot_rows(ds, ids))
    counts["transactions"] = bulk(session, txn, TXN_COLS, _txn_rows(ds, ids))
    _write_meta(session, ds)
    return counts
