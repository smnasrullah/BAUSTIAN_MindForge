"""Live synthetic data engine: the fixed generator's world, generated hour by hour for any date.

Determinism: every random draw comes from a generator seeded by (seed, purpose, calendar date
[, agent]), so the same date always produces the same demand, weather and anomalies, no matter
when or in how many batches it is generated. The float simulation is stateful (balances carry
over), and every balance is a whole BDT, so continuing from the balances stored in the database
gives exactly the values an uninterrupted run gives. Scheduled refills reset both floats to their
targets, so two runs started from different states agree from each agent's next refill on.

Agents are the fixed generator's agents (same seed stream). Effects: salary and factory wage days,
Eid rush and bank holidays and public holidays (data/holidays_bd.yaml), weekly hat-bazar, weather
for all months, the day-of-week profile, a slow trend from the fixed timeline's first day, ~3%
injected anomaly episodes (rolling 28-day blocks), and the demo stories (live_story.py).
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from functools import cached_property

import numpy as np

from app.models.enums import UrbanRural
from ml.data_gen import demo_spec
from ml.data_gen import live_calendar as lc
from ml.data_gen.agents import AgentSpec, build_agents
from ml.data_gen.anomalies import (
    ANOMALY_SHARE,
    CIRCULAR_TICKET,
    DURATION_DAYS,
    KINDS,
    NIGHT_HOURS,
    STRUCTURING_TICKET,
    AnomalyLabel,
)
from ml.data_gen.demand import (
    BASE_OUT,
    DAILY_NOISE_PHI,
    DAILY_NOISE_SIGMA,
    IN_RATIO,
    TICKET_IN,
    TICKET_OUT,
    TICKET_SIGMA,
)
from ml.data_gen.live_story import STORY_DISTRICT, Story
from ml.data_gen.simulate import ADHOC_HOURS, ADHOC_LOW_SHARE, ADHOC_PROB, _scaled_count, serve
from ml.data_gen.timeline import BDT

NOISE_K = 30  # the AR(1) daily noise as a fixed 30-day kernel (phi^30 ~ 2e-7)
BLOCK_DAYS = 28  # anomaly episodes are drawn per 28-day block from the trend epoch
TAG_NOISE, TAG_IN, TAG_OUT, TAG_ADHOC, TAG_ANOMALY, TAG_FX = 1, 2, 3, 4, 6, 7
PINNED = (demo_spec.STOCKOUT_AGENT, demo_spec.DONOR_AGENT, demo_spec.ANOMALY_AGENT)
H1 = timedelta(hours=1)


def _rng(*keys: int) -> np.random.Generator:
    return np.random.default_rng(list(keys))


def local(ts: datetime) -> datetime:
    return ts.astimezone(BDT)


@dataclass(frozen=True)
class LiveWorld:
    seed: int
    agents: tuple[AgentSpec, ...]
    holidays: tuple[lc.Holiday, ...]
    stories: tuple[Story, ...] = ()

    def index(self, code: str) -> int:
        return next(i for i, a in enumerate(self.agents) if a.code == code)

    @cached_property
    def wage_days(self) -> frozenset[tuple[str, date]]:
        return frozenset((STORY_DISTRICT, s.wage_day) for s in self.stories if s.wage_day)

    @cached_property
    def dry_days(self) -> frozenset[tuple[str, date]]:
        return frozenset((STORY_DISTRICT, d) for s in self.stories for d in s.dry_days)

    def with_stories(self, stories: tuple[Story, ...]) -> "LiveWorld":
        return LiveWorld(self.seed, self.agents, self.holidays, stories)


def build_world(seed: int, n_agents: int, stories: tuple[Story, ...] = ()) -> LiveWorld:
    """Same agents as ml/data_gen/dataset.py build_dataset (first spawned seed stream)."""
    r_world = np.random.default_rng(np.random.SeedSequence(seed).spawn(5)[0])
    return LiveWorld(seed, tuple(build_agents(n_agents, r_world)), lc.load_holidays(), stories)


@dataclass
class DayBlock:
    """One local day, all agents: arrays shaped (A, 24) unless noted."""

    lam_in: np.ndarray
    lam_out: np.ndarray
    amt_in: np.ndarray
    amt_out: np.ndarray
    cnt_in: np.ndarray
    cnt_out: np.ndarray
    scheduled: np.ndarray
    cash_target: np.ndarray  # (A,)
    adhoc_u: np.ndarray
    weather: dict[str, tuple[float, float, bool]]


@dataclass(frozen=True)
class Episode:
    agent: int
    kind: str
    first: date
    days: int

    def covers(self, d: date) -> bool:
        return self.first <= d < self.first + timedelta(days=self.days)


@dataclass
class Hour:
    """Hour t served; balances at the top of t + 1 after its refill (the next snapshot)."""

    ts: datetime
    served_in: np.ndarray
    served_out: np.ndarray
    cnt_in: np.ndarray
    cnt_out: np.ndarray
    cash_next: np.ndarray
    em_next: np.ndarray


@dataclass
class Engine:
    world: LiveWorld
    _eps: dict[int, np.ndarray] = field(default_factory=dict)
    _blocks: dict[date, DayBlock] = field(default_factory=dict)
    _combos: dict[tuple[UrbanRural, str, date], tuple[np.ndarray, np.ndarray]] = field(
        default_factory=dict)
    # Story agent's balances before this hour's refill (a suppressed refill keeps them).
    _prev: tuple[float, float] = (0.0, 0.0)

    def __post_init__(self) -> None:
        a = self.world.agents
        self.cash_cap = np.array([x.cash_capacity for x in a], dtype=float)
        self.em_cap = np.array([x.emoney_capacity for x in a], dtype=float)
        self.em_target = np.round(self.em_cap * np.array([x.emoney_target for x in a]))
        self.t_in = np.array([TICKET_IN[x.area] for x in a])
        self.t_out = np.array([TICKET_OUT[x.area] for x in a])
        self.daily_out = np.array([BASE_OUT[x.tier][x.area] * x.scale * x.out_bias for x in a])
        self.daily_in = np.array([BASE_OUT[x.tier][x.area] * IN_RATIO[x.area] * x.scale
                                  * x.in_bias for x in a])
        self.refill_wd = np.array([[wd in x.refill_weekdays for wd in range(7)] for x in a])
        self.refill_hour = np.array([x.refill_hour for x in a])
        codes = [x.code for x in a]
        self.pinned = {codes.index(c) for c in PINNED if c in codes}
        self.story_i = (codes.index(demo_spec.STOCKOUT_AGENT)
                        if demo_spec.STOCKOUT_AGENT in codes else None)
        self.anomaly_i = (codes.index(demo_spec.ANOMALY_AGENT)
                          if demo_spec.ANOMALY_AGENT in codes else None)

    # --- per-day draws -------------------------------------------------------------------------

    def weather(self, d: date) -> dict[str, tuple[float, float, bool]]:
        return lc.weather_of_day(self.world.seed, d, self.world.dry_days)

    def _eps_of(self, d: date) -> np.ndarray:
        key = d.toordinal()
        if key not in self._eps:
            self._eps[key] = _rng(self.world.seed, TAG_NOISE, key).normal(
                0.0, DAILY_NOISE_SIGMA, len(self.world.agents))
        return self._eps[key]

    def noise(self, d: date) -> np.ndarray:
        x = sum(DAILY_NOISE_PHI ** k * self._eps_of(d - timedelta(days=k)) for k in range(NOISE_K))
        return np.exp(np.asarray(x) - DAILY_NOISE_SIGMA ** 2 / 2)

    def expected(self, d: date) -> tuple[np.ndarray, np.ndarray]:
        """Noise-free hourly (cash_in, cash_out) BDT, (A, 24)."""
        w = self.weather(d)
        lam_in = np.zeros((len(self.world.agents), 24))
        lam_out = np.zeros_like(lam_in)
        for i, a in enumerate(self.world.agents):
            key = (a.area, a.district, d)
            if key not in self._combos:
                self._combos[key] = lc.hourly_calendar(a.area, a.district, d, self.world.holidays,
                                                       self.world.wage_days)
            c_out, c_in = self._combos[key]
            rain = lc.rain_multiplier(w[a.district][0], a.area)
            lam_in[i] = self.daily_in[i] * c_in * rain
            lam_out[i] = self.daily_out[i] * c_out * rain
        return lam_in, lam_out

    def episodes(self, d: date) -> list[Episode]:
        """Injected anomaly episodes of d's 28-day block (pinned demo agents never drawn)."""
        b = (d - lc.EPOCH).days // BLOCK_DAYS
        rng = _rng(self.world.seed, TAG_ANOMALY, b + 100_000)
        n_agents = len(self.world.agents)
        n = max(1, round(ANOMALY_SHARE * n_agents * BLOCK_DAYS / 120))
        pool = [i for i in range(n_agents) if i not in self.pinned]
        chosen = sorted(int(x) for x in rng.choice(pool, size=min(n, len(pool)), replace=False))
        out = []
        for k, i in enumerate(chosen):
            kind = KINDS[(b + k) % len(KINDS)]
            lo, hi = DURATION_DAYS[kind]
            length = int(rng.integers(lo, hi))
            off = int(rng.integers(0, BLOCK_DAYS - length + 1))
            first = lc.EPOCH + timedelta(days=b * BLOCK_DAYS + off)
            out.append(Episode(i, kind, first, length))
        return out

    def _inject(self, kind: str, i: int, d: date, hours: np.ndarray, blk: DayBlock) -> None:
        fx = _rng(self.world.seed, TAG_FX, d.toordinal(), i)
        if kind == "night_structuring":
            hours = hours[np.isin(hours, NIGHT_HOURS)]
            add_in, add_out = fx.poisson(12, hours.size), fx.poisson(10, hours.size)
            blk.cnt_in[i, hours] += add_in
            blk.cnt_out[i, hours] += add_out
            blk.amt_in[i, hours] += np.round(add_in * fx.uniform(*STRUCTURING_TICKET, hours.size))
            blk.amt_out[i, hours] += np.round(add_out * fx.uniform(*STRUCTURING_TICKET,
                                                                   hours.size))
        elif kind == "volume_burst":
            hours = hours[blk.lam_out[i, hours] > 0]
            k = fx.uniform(3.5, 5.5)
            for amt, cnt in ((blk.amt_in, blk.cnt_in), (blk.amt_out, blk.cnt_out)):
                amt[i, hours] = np.round(amt[i, hours] * k)
                cnt[i, hours] = np.round(cnt[i, hours] * k).astype(np.int64)
        elif kind == "circular_flow":
            hours = hours[blk.lam_out[i, hours] > 0]
            c = fx.poisson(15, hours.size)
            for amt, cnt in ((blk.amt_in, blk.cnt_in), (blk.amt_out, blk.cnt_out)):
                cnt[i, hours] += c
                amt[i, hours] += c * CIRCULAR_TICKET

    def _hours_of(self, d: date, start: datetime, end: datetime) -> np.ndarray:
        """Local hours of day d inside [start, end)."""
        day0 = datetime.combine(d, datetime.min.time(), tzinfo=BDT)
        return np.array([h for h in range(24) if start <= day0 + h * H1 < end], dtype=np.int64)

    def _apply_stories(self, d: date, blk: DayBlock) -> None:
        for s in self.world.stories:
            if self.story_i is not None:
                i = self.story_i
                hrs = self._hours_of(d, s.anchor, s.expected_until)
                for lam, amt, cnt, ticket in ((blk.lam_in, blk.amt_in, blk.cnt_in, self.t_in[i]),
                                              (blk.lam_out, blk.amt_out, blk.cnt_out,
                                               self.t_out[i])):
                    amt[i, hrs] = np.round(lam[i, hrs])
                    cnt[i, hrs] = np.where(amt[i, hrs] > 0,
                                           np.maximum(np.round(amt[i, hrs] / ticket), 1), 0)
            if self.anomaly_i is not None:
                hrs = self._hours_of(d, s.anomaly_start, s.anomaly_end)
                if hrs.size:
                    self._inject("night_structuring", self.anomaly_i, d, hrs, blk)

    def block(self, d: date) -> DayBlock:
        if d in self._blocks:
            return self._blocks[d]
        n = len(self.world.agents)
        lam_in, lam_out = self.expected(d)
        noise = self.noise(d)[:, None]
        amt_in, cnt_in = _realise(lam_in * noise, self.t_in[:, None],
                                  _rng(self.world.seed, TAG_IN, d.toordinal()))
        amt_out, cnt_out = _realise(lam_out * noise, self.t_out[:, None],
                                    _rng(self.world.seed, TAG_OUT, d.toordinal()))
        closed = lc.bank_closed(d, self.world.holidays)
        hours = np.arange(24)
        scheduled = (self.refill_wd[:, d.weekday()][:, None] & ~closed
                     & (hours[None, :] == self.refill_hour[:, None]))
        stock = lc.eid_stock_up(d, self.world.holidays)
        target = np.round(np.minimum(self.cash_cap * np.array(
            [a.cash_target for a in self.world.agents]) * stock, 0.95 * self.cash_cap))
        blk = DayBlock(lam_in, lam_out, amt_in, amt_out, cnt_in, cnt_out, scheduled, target,
                       _rng(self.world.seed, TAG_ADHOC, d.toordinal()).random((n, 24)),
                       self.weather(d))
        for ep in self.episodes(d):
            if ep.covers(d):
                self._inject(ep.kind, ep.agent, d, hours, blk)
        self._apply_stories(d, blk)
        self._blocks[d] = blk
        if len(self._blocks) > 8:  # a run walks forward: keep only the last few days
            self._blocks.pop(next(iter(self._blocks)))
        return blk

    # --- simulation ----------------------------------------------------------------------------

    def refill(self, t: datetime, cash: np.ndarray, em: np.ndarray
               ) -> tuple[np.ndarray, np.ndarray]:
        """Balances at the top of hour t after its refills (scheduled, ad-hoc, story)."""
        lt = local(t)
        blk, h = self.block(lt.date()), lt.hour
        mask = blk.scheduled[:, h].copy()
        if h in ADHOC_HOURS:
            low = (cash < ADHOC_LOW_SHARE * self.cash_cap) | (em < ADHOC_LOW_SHARE * self.em_cap)
            mask |= low & (blk.adhoc_u[:, h] < ADHOC_PROB)
        cash = np.where(mask, blk.cash_target, cash)
        em = np.where(mask, self.em_target, em)
        i = self.story_i
        if i is not None:
            for s in self.world.stories:
                if t == s.anchor:
                    cash[i], em[i] = s.refill_cash, self.em_target[i]
                elif s.anchor < t <= s.stockout_hour and mask[i]:
                    cash[i], em[i] = self._prev  # no refill until the story's stock-out
        return cash, em

    def _keep(self, cash: np.ndarray, em: np.ndarray) -> None:
        i = self.story_i
        self._prev = (float(cash[i]), float(em[i])) if i is not None else (0.0, 0.0)

    def step(self, t: datetime, cash: np.ndarray, em: np.ndarray) -> Hour:
        lt = local(t)
        blk, h = self.block(lt.date()), lt.hour
        d_in, d_out = blk.amt_in[:, h].astype(float), blk.amt_out[:, h].astype(float)
        s_in, s_out = serve(cash, em, d_in, d_out)
        c_in = _scaled_count(blk.cnt_in[:, h], s_in, d_in)
        c_out = _scaled_count(blk.cnt_out[:, h], s_out, d_out)
        cash_n, em_n = cash + s_in - s_out, em - s_in + s_out
        self._keep(cash_n, em_n)
        cash_n, em_n = self.refill(t + H1, cash_n, em_n)
        return Hour(t, s_in, s_out, c_in, c_out, cash_n, em_n)

    def start(self, t: datetime) -> tuple[np.ndarray, np.ndarray]:
        """Opening balances of a fresh window at hour t: the day's targets, then t's refills."""
        blk = self.block(local(t).date())
        cash, em = blk.cash_target.copy(), self.em_target.copy()
        self._keep(cash, em)
        return self.refill(t, cash, em)

    def run(self, t: datetime, cash: np.ndarray, em: np.ndarray, hours: int) -> Iterator[Hour]:
        """Serve hours t .. t + hours - 1 from the balances at the top of t."""
        for k in range(hours):
            out = self.step(t + k * H1, cash, em)
            cash, em = out.cash_next, out.em_next
            yield out

    def labels(self, first: date, last: date) -> list[AnomalyLabel]:
        """Injected episodes (and story anomalies) overlapping [first, last], for evaluation."""
        seen: dict[tuple[int, str, date], Episode] = {}
        b0, b1 = ((x - lc.EPOCH).days // BLOCK_DAYS for x in (first, last))
        for b in range(b0, b1 + 1):
            for ep in self.episodes(lc.EPOCH + timedelta(days=b * BLOCK_DAYS)):
                end = ep.first + timedelta(days=ep.days)
                if ep.first <= last and end > first:
                    seen[(ep.agent, ep.kind, ep.first)] = ep
        out = [AnomalyLabel(self.world.agents[e.agent].code, e.kind,
                            datetime.combine(e.first, datetime.min.time(), tzinfo=BDT),
                            datetime.combine(e.first + timedelta(days=e.days),
                                             datetime.min.time(), tzinfo=BDT))
               for e in seen.values()]
        out += [AnomalyLabel(demo_spec.ANOMALY_AGENT, "night_structuring", local(s.anomaly_start),
                             local(s.anomaly_end)) for s in self.world.stories]
        return sorted(out, key=lambda lab: (lab.window_start, lab.agent_code))


def _realise(lam: np.ndarray, ticket: np.ndarray, rng: np.random.Generator
             ) -> tuple[np.ndarray, np.ndarray]:
    """Same law as demand._realise: Poisson counts, log-normal ticket noise, whole BDT."""
    cnt = rng.poisson(lam / ticket)
    sigma = TICKET_SIGMA / np.sqrt(np.maximum(cnt, 1))
    amt = cnt * ticket * np.exp(rng.normal(0.0, 1.0, lam.shape) * sigma - sigma ** 2 / 2)
    return np.round(amt), cnt.astype(np.int64)


def utc(ts: datetime) -> datetime:
    return ts.astimezone(UTC)
