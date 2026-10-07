"""An agent's own refill habit, read from its history BEFORE the origin only.

A refill is an hour whose cash snapshot does not follow from the previous snapshot and that
hour's logged transactions: |cash[t] - (cash[t-1] + cash_in[t-1] - cash_out[t-1])| > REFILL_TOL_BDT
(a refill resets both floats to the agent's targets, so cash + e-money alone often does not
move). Per (weekday, local hour) slot: P(refill) = refills seen in that slot / times the slot
occurred in the last LOOKBACK_DAYS. Levels: the median balance of each float right after those
refills. Bank holidays are not known to the habit (a scheduled refill that a holiday cancels
still counts as likely).
"""

import numpy as np

from ml.inference.stockout_joint import Refill

LOOKBACK_DAYS = 42
REFILL_TOL_BDT = 10.0  # snapshots and amounts are rounded to whole BDT


def _slot(dow: np.ndarray, hod: np.ndarray) -> np.ndarray:
    return dow.astype(np.int64) * 24 + hod.astype(np.int64)


def refill_mask(cash: np.ndarray, served_in: np.ndarray, served_out: np.ndarray) -> np.ndarray:
    """(A, T) True where snapshot t breaks the transaction ledger (column 0: False).
    served_in / served_out[:, t] = BDT served in hour t (between snapshots t and t+1)."""
    expected = cash[:, :-1] + served_in[:, :-1] - served_out[:, :-1]
    jump = np.zeros(cash.shape, dtype=bool)
    with np.errstate(invalid="ignore"):
        jump[:, 1:] = np.abs(cash[:, 1:] - expected) > REFILL_TOL_BDT
    return jump


def habits(cash: np.ndarray, em: np.ndarray, served_in: np.ndarray, served_out: np.ndarray,
           dow: np.ndarray, hod: np.ndarray, t0: int, horizon: int,
           lookback_days: int = LOOKBACK_DAYS) -> list[Refill]:
    """One Refill per agent for the hours t0 .. t0 + horizon - 1.

    cash / em: (A, T) balance at the top of each hour index (nan = no snapshot); served_in /
    served_out: (A, T) BDT served in each hour. Only columns t0 - lookback .. t0 are read.
    dow / hod: (>= t0 + horizon,) calendar of every hour index. prob[0] = 0: a refill at the
    origin hour is already in the opening balance.
    """
    lo = max(1, t0 - lookback_days * 24 + 1)
    span = slice(lo, t0 + 1)
    window = slice(lo - 1, t0 + 1)
    jump = refill_mask(cash[:, window], served_in[:, window], served_out[:, window])[:, 1:]
    slots = _slot(dow[span], hod[span])
    seen = np.bincount(slots, minlength=7 * 24).astype(float)
    future = _slot(dow[t0:t0 + horizon], hod[t0:t0 + horizon])
    out: list[Refill] = []
    for a in range(cash.shape[0]):
        when = np.flatnonzero(jump[a])
        if len(when) == 0:
            out.append(Refill(np.zeros(horizon), 0.0, 0.0))
            continue
        hits = np.bincount(slots[when], minlength=7 * 24).astype(float)
        prob = np.divide(hits, seen, out=np.zeros_like(hits), where=seen > 0)[future]
        prob[0] = 0.0
        at = when + lo
        out.append(Refill(prob, float(np.median(cash[a, at])), float(np.median(em[a, at]))))
    return out
