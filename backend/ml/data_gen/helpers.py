"""SIMULATED helper behaviour for liquidity help requests (learning to match).

Nothing here is measured: the acceptance law in `Behaviour` is an assumption written for the
synthetic world, so a model learned from it only shows that the method can recover such a law.
Real response data is needed before any claim about real helpers.

World (fixed seed, separate random stream; the stored dataset is unchanged):
- requests: a business hour (08-20) where an agent's float is below LOW_SHARE of capacity, at
  most one per agent and float per day, half of those hours kept;
- the rule-feasible helpers of a request mirror app/services/help_trigger.py: same distributor,
  within RADIUS_KM, not opted out, not the requester, not asked in the last RECENT_ASK_H, and a
  surplus (balance above BUFFER_SHARE of capacity) that covers the whole amount;
- each asked helper says yes with the hidden probability of `Behaviour` (distance, hour, asks
  in the last 7 days, own surplus ratio, tier, a personal propensity), answers within minutes,
  or lets the wave time out. A request is covered by the first yes; waves of up to WAVE_SIZE go
  every WAVE_MIN minutes, at most MAX_WAVES.
Common random numbers: the yes/no draw and the answer time of (request, helper) are fixed, so
every ranking policy meets the same people in the same mood.
"""

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from ml.data_gen.dataset import Dataset
from ml.data_gen.timeline import N_HOURS, hour_of_day
from ml.inference.helper_accept import FEATURES, feature_row, hour_band

RADIUS_KM = 5.0
WAVE_SIZE = 5
MAX_WAVES = 3
WAVE_MIN = 15
RECENT_ASK_H = 2
ASK_WINDOW_H = 168
BUFFER_SHARE = 0.25
LOW_SHARE = 0.12
REQUEST_KEEP = 0.5
TARGET_SHARE = 0.5  # a request asks to refill to this share of capacity
ROUND_BDT = 1_000
MAX_REQUEST_BDT = 200_000
OPT_OUT_SHARE = 0.10
STREAM = 9_001  # rng stream id: (seed, STREAM, ...) never collides with the dataset's streams
FLOATS = ("cash", "emoney")


@dataclass(frozen=True)
class Behaviour:
    """The hidden acceptance law (log-odds terms). ASSUMED, not measured."""

    intercept: float = 0.6
    per_km: float = -0.45
    busy: float = 0.3  # 10:00-17:59
    edge: float = -0.3  # 08:00-09:59 and 18:00-20:59
    night: float = -1.2
    per_recent_ask: float = -0.35  # each ask in the last 7 days
    per_log_surplus: float = 0.6  # log(surplus / amount)
    tier: tuple[float, float, float] = (0.2, 0.0, -0.2)
    propensity_sd: float = 0.8  # personal, persistent
    answer_median_min: float = 6.0
    decline_answers: float = 0.5  # share of no's that are said (else the wave times out)


@dataclass(frozen=True)
class Request:
    rid: int
    t: int  # hour index (top of the hour)
    row: int  # requester
    float_type: str
    amount: float


@dataclass(frozen=True)
class Candidate:
    row: int
    distance_km: float
    surplus: float


@dataclass
class HelperState:
    """What the system has seen: ask times and answers per helper (history before now)."""

    ask_times: dict[int, deque[float]] = field(default_factory=dict)  # hours
    asked: dict[int, int] = field(default_factory=dict)
    accepted: dict[int, int] = field(default_factory=dict)

    def asks_in_window(self, row: int, now: float) -> int:
        q = self.ask_times.get(row)
        if not q:
            return 0
        while q and q[0] <= now - ASK_WINDOW_H:
            q.popleft()
        return len(q)

    def last_ask(self, row: int) -> float | None:
        q = self.ask_times.get(row)
        return q[-1] if q else None

    def record(self, row: int, now: float, yes: bool) -> None:
        self.ask_times.setdefault(row, deque()).append(now)
        self.asked[row] = self.asked.get(row, 0) + 1
        self.accepted[row] = self.accepted.get(row, 0) + int(yes)

    def copy(self) -> "HelperState":
        return HelperState({k: deque(v) for k, v in self.ask_times.items()}, dict(self.asked),
                           dict(self.accepted))


@dataclass
class World:
    seed: int
    lat: np.ndarray
    lng: np.ndarray
    distributor: np.ndarray
    tier: np.ndarray
    cash: np.ndarray  # (A, T) balance at the top of each hour
    emoney: np.ndarray
    cash_cap: np.ndarray
    emoney_cap: np.ndarray
    propensity: np.ndarray  # (A,) hidden
    opted_out: np.ndarray  # (A,) bool
    km: np.ndarray  # (A, A) distance, inf across distributors
    behaviour: Behaviour

    def balance(self, f: str) -> np.ndarray:
        return self.cash if f == "cash" else self.emoney

    def capacity(self, f: str) -> np.ndarray:
        return self.cash_cap if f == "cash" else self.emoney_cap


def _km(lat: np.ndarray, lng: np.ndarray) -> np.ndarray:
    p = np.radians(lat)[:, None], np.radians(lat)[None, :]
    dl = np.radians(lng)[None, :] - np.radians(lng)[:, None]
    a = np.sin((p[1] - p[0]) / 2) ** 2 + np.cos(p[0]) * np.cos(p[1]) * np.sin(dl / 2) ** 2
    return 2 * 6371.0088 * np.arcsin(np.sqrt(np.minimum(1.0, a)))


def build_world(ds: Dataset, behaviour: Behaviour | None = None) -> World:
    rng = np.random.default_rng([ds.seed, STREAM, 0])
    agents = ds.agents
    dist = np.array([a.distributor_code for a in agents])
    km = _km(np.array([a.lat for a in agents]), np.array([a.lng for a in agents]))
    km[dist[:, None] != dist[None, :]] = np.inf
    b = behaviour or Behaviour()
    return World(
        seed=ds.seed, lat=np.array([a.lat for a in agents]), lng=np.array([a.lng for a in agents]),
        distributor=dist, tier=np.array([a.tier for a in agents]),
        cash=ds.floats.cash, emoney=ds.floats.emoney,
        cash_cap=np.array([float(a.cash_capacity) for a in agents]),
        emoney_cap=np.array([float(a.emoney_capacity) for a in agents]),
        propensity=rng.normal(0.0, b.propensity_sd, len(agents)),
        opted_out=rng.random(len(agents)) < OPT_OUT_SHARE, km=km, behaviour=b)


def requests(w: World) -> list[Request]:
    rng = np.random.default_rng([w.seed, STREAM, 1])
    hod = hour_of_day()
    out: list[Request] = []
    last: dict[tuple[int, str], int] = {}
    for t in range(N_HOURS):
        if not 8 <= hod[t] <= 20:
            continue
        for f in FLOATS:
            bal, cap = w.balance(f)[:, t], w.capacity(f)
            for row in np.flatnonzero(bal < LOW_SHARE * cap).tolist():
                if t - last.get((row, f), -10**9) < 24 or rng.random() >= REQUEST_KEEP:
                    continue
                last[(row, f)] = t
                need = TARGET_SHARE * cap[row] - bal[row]
                amount = min(math.ceil(need / ROUND_BDT) * ROUND_BDT, MAX_REQUEST_BDT)
                out.append(Request(len(out), t, row, f, float(amount)))
    return out


def feasible(w: World, req: Request, state: HelperState, exclude: set[int]) -> list[Candidate]:
    """The rule-feasible helpers (rules decide; the ranking only orders this set)."""
    bal, cap = w.balance(req.float_type)[:, req.t], w.capacity(req.float_type)
    surplus = bal - BUFFER_SHARE * cap
    near = np.flatnonzero((w.km[req.row] <= RADIUS_KM) & ~w.opted_out & (surplus >= req.amount))
    out = []
    for row in near.tolist():
        last = state.last_ask(row)
        if row == req.row or row in exclude or (last is not None
                                                and req.t - last < RECENT_ASK_H):
            continue
        out.append(Candidate(row, float(w.km[req.row, row]), float(surplus[row])))
    return out


def true_p(w: World, req: Request, c: Candidate, state: HelperState) -> float:
    b = w.behaviour
    band = hour_band(int(hour_of_day()[req.t]))
    z = (b.intercept + b.per_km * c.distance_km
         + {"busy": b.busy, "edge": b.edge, "night": b.night}[band]
         + b.per_recent_ask * state.asks_in_window(c.row, req.t)
         + b.per_log_surplus * math.log(max(c.surplus / req.amount, 1.0))
         + b.tier[int(w.tier[c.row]) - 1] + w.propensity[c.row])
    return 1.0 / (1.0 + math.exp(-z))


def draws(w: World, req: Request, row: int) -> tuple[float, float, float]:
    """Common random numbers of (request, helper): yes draw, answer minutes, says-no draw."""
    rng = np.random.default_rng([w.seed, STREAM, 2, req.rid, row])
    u, z, v = rng.random(), rng.standard_normal(), rng.random()
    return u, w.behaviour.answer_median_min * math.exp(0.6 * z), v


# --- features the system can see at ask time (ml/inference/helper_accept.py) --------------


def features(w: World, req: Request, c: Candidate, state: HelperState) -> list[float]:
    return feature_row(c.distance_km, int(hour_of_day()[req.t]),
                       state.asks_in_window(c.row, req.t), c.surplus, req.amount,
                       int(w.tier[c.row]), state.asked.get(c.row, 0),
                       state.accepted.get(c.row, 0))


# --- one request, wave by wave ------------------------------------------------------------------

Ranker = Callable[[World, Request, list[Candidate], HelperState], list[Candidate]]
WaveSizer = Callable[[World, Request, list[Candidate], HelperState, int], int]


def fixed_waves(_w: World, _r: Request, _c: list[Candidate], _s: HelperState, cap: int) -> int:
    return cap


@dataclass
class Outcome:
    covered: bool
    asks: int
    yes: int
    minutes: float | None  # from the first wave to the first yes
    asked_rows: list[int]


def run_request(w: World, req: Request, rank: Ranker, size: WaveSizer, state: HelperState,
                log: list[dict[str, float]] | None = None) -> Outcome:
    asked: set[int] = set()
    asks = yes = 0
    best: float | None = None
    rows: list[int] = []
    for wave in range(MAX_WAVES):
        pool = rank(w, req, feasible(w, req, state, asked), state)
        if not pool:
            break
        take = pool[:max(1, min(WAVE_SIZE, size(w, req, pool, state, WAVE_SIZE)))]
        start = wave * WAVE_MIN
        answers = []
        for c in take:
            p = true_p(w, req, c, state)
            u, minutes, _ = draws(w, req, c.row)
            ok = u < p
            if log is not None:
                log.append({"rid": req.rid, "t": req.t, "row": c.row, "wave": wave,
                            "y": float(ok), "p_true": p,
                            **dict(zip(FEATURES, features(w, req, c, state), strict=True))})
            answers.append((c.row, ok, start + minutes))
        for row, ok, at in answers:  # the state moves once the whole wave has been asked
            state.record(row, req.t + (start / 60.0), ok)
            asked.add(row)
            rows.append(row)
            asks += 1
            yes += int(ok)
            if ok and at <= start + WAVE_MIN and (best is None or at < best):
                best = at
        if best is not None:
            break
    return Outcome(best is not None, asks, yes, best, rows)


def by_distance(_w: World, _r: Request, pool: list[Candidate], _s: HelperState
                ) -> list[Candidate]:
    return sorted(pool, key=lambda c: (c.distance_km, c.row))


def exploring(noise_km: float, seed: int) -> Ranker:
    """Logging policy of the simulated history: distance plus random noise (exploration), so
    the history holds far and near, rested and busy helpers alike."""

    def rank(w: World, req: Request, pool: list[Candidate], _s: HelperState
             ) -> list[Candidate]:
        rng = np.random.default_rng([seed, STREAM, 3, req.rid])
        noise = rng.normal(0.0, noise_km, len(pool))
        order = np.argsort([c.distance_km + e for c, e in zip(pool, noise, strict=True)],
                           kind="stable")
        return [pool[i] for i in order]
    return rank


def history(w: World, reqs: list[Request], until_t: int, noise_km: float = 1.5
            ) -> tuple[list[dict[str, float]], HelperState]:
    """Asks and answers of every request before `until_t` under the logging policy."""
    state = HelperState()
    log: list[dict[str, float]] = []
    rank = exploring(noise_km, w.seed)
    for req in reqs:
        if req.t >= until_t:
            break
        run_request(w, req, rank, fixed_waves, state, log)
    return log, state
