"""History behind the refill-aware view: the last refill.LOOKBACK_DAYS of balances and served BDT.

About 300k snapshots and 330k transactions for 300 agents. Postgres: the database casts to
float8 and epoch seconds, and numpy scatters the columns (no per-row Decimal, datetime or enum
decoding; ~3.7 s -> ~1.5 s per live tick). Other databases (SQLite tests): one Python loop. Both
give the same arrays: each float is the correctly rounded NUMERIC, and transactions are added
in row order.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import Float, Select, case, cast, func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.models import FloatSnapshot, Transaction
from app.models.enums import TxnType
from ml.data_gen.timeline import BDT
from ml.inference import refill


@dataclass
class History:
    """The last refill.LOOKBACK_DAYS up to `now` (column t0), for the refill habit."""

    cash: np.ndarray  # (A, T) top-of-hour balances, nan = no snapshot
    emoney: np.ndarray
    served_in: np.ndarray  # (A, T) BDT served in each hour
    served_out: np.ndarray
    dow: np.ndarray  # (T + horizon,) local calendar
    hod: np.ndarray
    t0: int


def _epoch(col: Any) -> Any:
    return cast(func.extract("epoch", col), Float)


def _columns(session: Session, query: Select[Any], n: int) -> np.ndarray:
    """(rows, n) float64 array of a query's columns (agent id and epoch included)."""
    found = [tuple(r) for r in session.execute(query)]  # np.array over Row objects is 20x slower
    return np.array(found, dtype=np.float64).reshape(len(found), n)


def _scatter(cols: np.ndarray, rows: np.ndarray, first: datetime, span: int
             ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(keep mask, row index, hour index) of each fetched row: known agent, inside the span."""
    aid = cols[:, 0].astype(np.int64)
    known = (aid >= 0) & (aid < len(rows))
    r = np.where(known, rows[np.clip(aid, 0, len(rows) - 1)], -1)
    t = np.floor((cols[:, 1] - first.timestamp()) / 3600.0).astype(np.int64)
    keep = (r >= 0) & (t >= 0) & (t <= span)
    return keep, r[keep], t[keep]


def _fill_postgres(session: Session, first: datetime, now: datetime, agent_ids: Sequence[int],
                   cash: np.ndarray, em: np.ndarray, served: dict[TxnType, np.ndarray]) -> None:
    span = cash.shape[1] - 1
    rows = np.full(max(agent_ids) + 1, -1, dtype=np.int64)
    rows[np.asarray(agent_ids, dtype=np.int64)] = np.arange(len(agent_ids))
    snaps = _columns(session, select(
        FloatSnapshot.agent_id, _epoch(FloatSnapshot.ts), cast(FloatSnapshot.cash_balance, Float),
        cast(FloatSnapshot.emoney_balance, Float)).where(
            FloatSnapshot.ts >= first, FloatSnapshot.ts <= now), 4)
    keep, r, t = _scatter(snaps, rows, first, span)
    cash[r, t], em[r, t] = snaps[keep, 2], snaps[keep, 3]
    kinds = list(served)
    code = case(*((Transaction.txn_type == k, i) for i, k in enumerate(kinds)), else_=-1)
    txns = _columns(session, select(
        Transaction.agent_id, _epoch(Transaction.ts), cast(Transaction.amount_bdt, Float), code)
        .where(Transaction.ts >= first, Transaction.ts < now), 4)
    keep, r, t = _scatter(txns, rows, first, span)
    kind, amount = txns[keep, 3], txns[keep, 2]
    for i, k in enumerate(kinds):
        mine = kind == i
        np.add.at(served[k], (r[mine], t[mine]), amount[mine])  # row order, as _fill_rows


def _fill_rows(session: Session, first: datetime, now: datetime, agent_ids: Sequence[int],
               cash: np.ndarray, em: np.ndarray, served: dict[TxnType, np.ndarray]) -> None:
    span = cash.shape[1] - 1
    row = {a: i for i, a in enumerate(agent_ids)}

    def at(ts: datetime) -> int:
        return int((clock.as_utc(ts) - first) // timedelta(hours=1))

    for aid, ts, c, e in session.execute(
            select(FloatSnapshot.agent_id, FloatSnapshot.ts, FloatSnapshot.cash_balance,
                   FloatSnapshot.emoney_balance).where(FloatSnapshot.ts >= first,
                                                       FloatSnapshot.ts <= now)).tuples():
        t, r = at(ts), row.get(aid)
        if r is not None and 0 <= t <= span:
            cash[r, t], em[r, t] = float(c), float(e)
    for aid, ts, kind, amount in session.execute(
            select(Transaction.agent_id, Transaction.ts, Transaction.txn_type,
                   Transaction.amount_bdt).where(Transaction.ts >= first,
                                                 Transaction.ts < now)).tuples():
        t, r = at(ts), row.get(aid)
        if r is not None and 0 <= t <= span:
            served[TxnType(kind)][r, t] += float(amount)


def load_history(session: Session, now: datetime, agent_ids: list[int], horizon: int
                 ) -> History:
    span = refill.LOOKBACK_DAYS * 24
    first = clock.as_utc(now) - timedelta(hours=span)
    cash = np.full((len(agent_ids), span + 1), np.nan)
    em = np.full_like(cash, np.nan)
    served = {k: np.zeros_like(cash) for k in TxnType}
    if agent_ids:
        fill = _fill_postgres if session.get_bind().dialect.name == "postgresql" else _fill_rows
        fill(session, first, clock.as_utc(now), agent_ids, cash, em, served)
    hours = [(first + timedelta(hours=k)).astimezone(BDT) for k in range(span + horizon + 1)]
    return History(cash, em, served[TxnType.cash_in], served[TxnType.cash_out],
                   np.array([h.weekday() for h in hours], dtype=np.int64),
                   np.array([h.hour for h in hours], dtype=np.int64), span)
