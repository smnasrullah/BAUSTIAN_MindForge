"""Per-agent window features for the anomaly detector (F9).

A window is the WINDOW_H hours before hour index `end` (exclusive); the agent's own baseline is
the HISTORY_H hours before the window. Every measure becomes a robust z vs the agent's peer group
in the same window, so market-wide shifts (Eid, salary days) cancel. A served artifact names the
model inputs it uses (FeatureSpec); every input listed in MEASURES can be computed, so an older
artifact keeps scoring after new inputs are added.

Refills: a refill is a snapshot whose cash is not explained by the previous snapshot and that
hour's logged transactions (ml/inference/refill.py, the "ledger" rule). The older rule, "cash +
e-money jumped", misses most refills (a refill resets both floats to targets, so the total often
does not move); it stays only for the iforest 1.0.0 artifacts (input `refills_peer_z`).

Volume bursts: each day of the window (24 h blocks counted back from `end`) is compared with the
same day of the week in the agent's own history (ratio of cash-in + cash-out, floored by
DAY_FLOOR_BDT): the peak ratio, the days at or above `burst_k` times usual, and the largest
day-over-day jump of that ratio (the day before the window is the first reference).
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np
from scipy.spatial.distance import jensenshannon
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Agent
from app.models.enums import TxnType, UrbanRural
from app.models.timeseries import FloatSnapshot, Transaction
from ml.data_gen.timeline import FIXED, Window
from ml.inference.refill import refill_mask

WINDOW_H = 7 * 24
HISTORY_H = 28 * 24
STRIDE_H = 24
DAY_H = 24
WEEK_H = 7 * 24
REFILL_MIN_BDT = 10.0  # snapshots round each float to 1 BDT; a refill moves the total far more
DAY_FLOOR_BDT = 1_000.0  # keeps near-empty days from producing huge burst ratios
MIN_PEERS = 10  # smaller tier x area groups use the global group
GLOBAL_GROUP = "all"
Z_FLOOR = 0.05  # floor of the robust spread, so a flat peer group does not divide by ~0
DEFAULT_BURST_K = 2.0
# Model input -> (raw window measure shown as evidence, one-sided). One-sided: only "more than
# peers" is suspicious, below-peer values are clipped to 0.
MEASURES: dict[str, tuple[str, bool]] = {
    "cash_out_peer_z": ("cash_out_growth", True),
    "hour_shift_peer_z": ("hour_shift", True),
    "refills_peer_z": ("refills_per_day", True),  # total-float rule (iforest 1.0.0)
    "ledger_refills_peer_z": ("refills_per_day", True),  # transaction-ledger rule
    "out_in_ratio_peer_z": ("out_in_log_ratio", False),
    "burst_peak_peer_z": ("burst_peak_ratio", True),
    "burst_days_peer_z": ("burst_days", True),
    "rate_change_peer_z": ("rate_change", True),
}
LEGACY_FEATURES = ("cash_out_peer_z", "hour_shift_peer_z", "refills_peer_z",
                   "out_in_ratio_peer_z")
LEDGER_FEATURES = ("cash_out_peer_z", "hour_shift_peer_z", "ledger_refills_peer_z",
                   "out_in_ratio_peer_z")
BURST_FEATURES = ("burst_peak_peer_z", "burst_days_peer_z", "rate_change_peer_z")


@dataclass(frozen=True)
class FeatureSpec:
    """Model inputs of one detector, in column order, and the burst-day threshold."""

    features: tuple[str, ...] = LEGACY_FEATURES
    burst_k: float = DEFAULT_BURST_K

    def __post_init__(self) -> None:
        unknown = [f for f in self.features if f not in MEASURES]
        if unknown or not self.features:
            raise ValueError(f"unknown anomaly inputs: {unknown}")
        if "refills_peer_z" in self.features and "ledger_refills_peer_z" in self.features:
            raise ValueError("use one refill rule")

    @property
    def raw_names(self) -> tuple[str, ...]:
        return tuple(MEASURES[f][0] for f in self.features)

    @property
    def ledger(self) -> bool:
        return "refills_peer_z" not in self.features


@dataclass
class Series:
    agent_ids: np.ndarray  # (A,) agents.id, ordered by id
    codes: list[str]
    groups: list[str]  # peer group per agent
    cash_out: np.ndarray  # (A, n_hours) BDT served
    cash_in: np.ndarray  # (A, n_hours) BDT served
    total: np.ndarray  # (A, n_hours) cash + e-money at the top of the hour; nan = no snapshot
    window: Window = field(default=FIXED)
    cash: np.ndarray | None = None  # (A, n_hours) cash at the top of the hour; nan = no snapshot


def group_key(tier: int, area: UrbanRural) -> str:
    return f"t{tier}-{UrbanRural(area).value}"


def assign_groups(keys: list[str]) -> list[str]:
    counts = Counter(keys)
    return [k if counts[k] >= MIN_PEERS else GLOBAL_GROUP for k in keys]


def _utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts


def load_series(session: Session, end: int | None = None, window: Window = FIXED,
                since: int = 0) -> Series:
    """Hourly flows and float balances; nothing at or after hour index `end` (nor before
    `since`) is read. A scan needs only the window + history before `end` (live ticks pass
    `since`)."""
    end = window.n_hours if end is None else end
    agents = list(session.scalars(select(Agent).order_by(Agent.id)))
    row_of = {a.id: i for i, a in enumerate(agents)}
    shape = (len(agents), window.n_hours)
    flows = {TxnType.cash_out: np.zeros(shape), TxnType.cash_in: np.zeros(shape)}
    total, cash_bal = np.full(shape, np.nan), np.full(shape, np.nan)
    stop, first = window.ts_of(end), window.ts_of(max(since, 0))
    for aid, ts, kind, amount in session.execute(
            select(Transaction.agent_id, Transaction.ts, Transaction.txn_type,
                   Transaction.amount_bdt).where(Transaction.ts < stop, Transaction.ts >= first)):
        t, r = window.hour_index(_utc(ts)), row_of.get(aid)
        if r is not None and 0 <= t < end:
            flows[TxnType(kind)][r, t] += float(amount)
    for aid, ts, cash, em in session.execute(
            select(FloatSnapshot.agent_id, FloatSnapshot.ts, FloatSnapshot.cash_balance,
                   FloatSnapshot.emoney_balance).where(FloatSnapshot.ts < stop,
                                                       FloatSnapshot.ts >= first)):
        t, r = window.hour_index(_utc(ts)), row_of.get(aid)
        if r is not None and 0 <= t < end:
            total[r, t] = float(cash) + float(em)
            cash_bal[r, t] = float(cash)
    return Series(
        agent_ids=np.array([a.id for a in agents], dtype=np.int64),
        codes=[a.code for a in agents],
        groups=assign_groups([group_key(a.tier, a.urban_rural) for a in agents]),
        cash_out=flows[TxnType.cash_out], cash_in=flows[TxnType.cash_in], total=total,
        window=window, cash=cash_bal,
    )


def robust_z(values: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """(value - group median) / (1.4826 x group MAD), spread floored at Z_FLOOR."""
    z = np.zeros_like(values, dtype=float)
    for g in np.unique(groups):
        m = groups == g
        med = np.median(values[m])
        spread = max(1.4826 * float(np.median(np.abs(values[m] - med))), Z_FLOOR)
        z[m] = (values[m] - med) / spread
    return z


def hour_profile(amounts: np.ndarray, first_hour: int) -> np.ndarray:
    """(A, 24) amount per local hour of day; hour index 0 is local midnight."""
    hod = (first_hour + np.arange(amounts.shape[1])) % 24
    return np.stack([amounts[:, hod == h].sum(axis=1) for h in range(24)], axis=1)


def hour_shift(window: np.ndarray, history: np.ndarray) -> np.ndarray:
    """Jensen-Shannon distance (base 2, 0..1) between two (A, 24) hour profiles."""
    ok = (window.sum(axis=1) > 0) & (history.sum(axis=1) > 0)
    out = np.zeros(window.shape[0])
    if ok.any():
        out[ok] = jensenshannon(window[ok], history[ok], axis=1, base=2)
    return np.nan_to_num(out)


def refill_count(total: np.ndarray) -> np.ndarray:
    """Old rule: hours whose total float differs from the previous hour's; total has one
    leading hour."""
    with np.errstate(invalid="ignore"):
        return (np.abs(np.diff(total, axis=1)) > REFILL_MIN_BDT).sum(axis=1)


def ledger_refill_count(cash: np.ndarray, served_in: np.ndarray, served_out: np.ndarray
                        ) -> np.ndarray:
    """Ledger rule: snapshots that break the transaction ledger; arrays have one leading hour."""
    return refill_mask(cash, served_in, served_out)[:, 1:].sum(axis=1)


def day_ratios(volume: np.ndarray, end: int) -> np.ndarray:
    """(A, 8): the day before the window and the 7 window days, each as (volume + floor) /
    (mean volume of the same weekday in the history + floor). Days are 24 h blocks ending at
    `end`; only history blocks at or after end - WINDOW_H - HISTORY_H are references."""
    w0, h0 = end - WINDOW_H, end - WINDOW_H - HISTORY_H
    out = np.empty((volume.shape[0], WINDOW_H // DAY_H + 1))
    for k, b in enumerate(range(w0 - DAY_H, end, DAY_H)):
        refs = [r for r in range(b - WEEK_H, h0 - 1, -WEEK_H)][:HISTORY_H // WEEK_H]
        usual = np.mean([volume[:, r:r + DAY_H].sum(axis=1) for r in refs], axis=0)
        out[:, k] = (volume[:, b:b + DAY_H].sum(axis=1) + DAY_FLOOR_BDT) / (usual + DAY_FLOOR_BDT)
    return out


@dataclass(frozen=True)
class Window:
    names: tuple[str, ...]  # raw measure per column
    raw: np.ndarray  # (A, len(names))
    x: np.ndarray  # (A, len(names)) model input
    cash_out_bdt: np.ndarray  # (A,) window totals, kept as evidence
    cash_in_bdt: np.ndarray
    baseline_cash_out_bdt: np.ndarray  # own history rate scaled to the window length
    refills: np.ndarray  # refills in the window, by the spec's rule


def window_features(s: Series, end: int, spec: FeatureSpec | None = None) -> Window:
    spec = spec or FeatureSpec()
    w0, h0 = end - WINDOW_H, end - WINDOW_H - HISTORY_H
    if h0 < 0 or end > s.window.n_hours:
        raise ValueError(f"window ending at hour {end} lacks history")
    out_w, in_w = s.cash_out[:, w0:end].sum(axis=1), s.cash_in[:, w0:end].sum(axis=1)
    out_base = s.cash_out[:, h0:w0].sum(axis=1) * WINDOW_H / HISTORY_H
    if spec.ledger:
        if s.cash is None:
            raise ValueError("ledger refills need the cash balances")
        lead = slice(w0 - 1, end)
        refills = ledger_refill_count(s.cash[:, lead], s.cash_in[:, lead], s.cash_out[:, lead])
    else:
        refills = refill_count(s.total[:, w0 - 1:end])
    cols: dict[str, np.ndarray] = {}
    if set(spec.raw_names) & {"burst_peak_ratio", "burst_days", "rate_change"}:
        ratio = day_ratios(s.cash_out + s.cash_in, end)
    for name in spec.raw_names:
        if name == "cash_out_growth":
            cols[name] = np.log((out_w + 1) / (out_base + 1))
        elif name == "hour_shift":
            flow = s.cash_out + s.cash_in
            cols[name] = hour_shift(hour_profile(flow[:, w0:end], w0),
                                    hour_profile(flow[:, h0:w0], h0))
        elif name == "refills_per_day":
            cols[name] = refills / (WINDOW_H / DAY_H)
        elif name == "out_in_log_ratio":
            cols[name] = np.log((out_w + 1) / (in_w + 1))
        elif name == "burst_peak_ratio":
            cols[name] = ratio[:, 1:].max(axis=1)
        elif name == "burst_days":
            cols[name] = (ratio[:, 1:] >= spec.burst_k).sum(axis=1).astype(float)
        else:  # rate_change
            cols[name] = (ratio[:, 1:] / ratio[:, :-1]).max(axis=1)
    raw = np.column_stack([cols[n] for n in spec.raw_names])
    groups = np.array(s.groups)
    x = np.column_stack([robust_z(raw[:, j], groups) for j in range(raw.shape[1])])
    one_sided = [MEASURES[f][1] for f in spec.features]
    x[:, one_sided] = np.maximum(x[:, one_sided], 0)
    return Window(spec.raw_names, raw, x, out_w, in_w, out_base, refills)
