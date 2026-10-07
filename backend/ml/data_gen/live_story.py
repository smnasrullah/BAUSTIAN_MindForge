"""The demo story on the live clock, anchored at an hour instead of the fixed SIM_NOW.

At the anchor hour the story agent (demo_spec.STOCKOUT_AGENT) gets a cash top-up that is solved
backwards so that, on its expected demand and with no refill in between, cash runs out at
STOCKOUT_LOCAL on the next feasible afternoon (today or tomorrow, at least MIN_LEAD_H ahead).
The donor (DONOR_AGENT) is a nearby agent of the same distributor. The anomaly agent shows night
structuring around the anchor. When no real calendar event explains the rush, the story adds a
clearly labelled demo event (a factory wage day in Dhaka) to the world AND the events table.

Stories are stored in system_meta (demo_story) so catch-up and backtests replay them exactly.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from ml.data_gen.timeline import BDT

STOCKOUT_LOCAL = time(15, 40)
MIN_LEAD_H = 4.0
CANDIDATE_DAYS = 3  # today, tomorrow, the day after
STORY_DISTRICT = "Dhaka"
DEMO_EVENT_EN = "Demo event: Mirpur factory wage day (synthetic)"
DEMO_EVENT_BN = "ডেমো ইভেন্ট: মিরপুর কারখানার মজুরি দিবস (সিন্থেটিক)"
FRESH_ANOMALY_DAYS = 6  # night structuring from 6 days before a fresh anchor ...
ANOMALY_AFTER_H = 24  # ... to a day after it
REANCHOR_ANOMALY_H = 72  # a later re-anchor cannot rewrite the past: 3 nights from the anchor


@dataclass(frozen=True)
class Story:
    anchor: datetime  # UTC hour of the top-up (also the forecast origin when it was planned)
    stockout_at: datetime  # UTC, minute precision
    refill_cash: float
    anomaly_start: datetime
    anomaly_end: datetime
    wage_day: date | None  # demo wage event day (Dhaka) or None when the calendar explains it
    dry_days: tuple[date, ...] = field(default=())  # Dhaka kept dry: the wage day is the "why"

    @property
    def stockout_hour(self) -> datetime:
        return self.stockout_at.replace(minute=0)

    @property
    def expected_until(self) -> datetime:
        """End of the stock-out's local day: the story agent follows expected demand until then."""
        local = self.stockout_at.astimezone(BDT).date() + timedelta(days=1)
        return datetime.combine(local, time(0), tzinfo=BDT)

    def as_json(self) -> dict[str, Any]:
        return {"anchor": self.anchor.isoformat(), "stockout_at": self.stockout_at.isoformat(),
                "refill_cash": self.refill_cash, "anomaly_start": self.anomaly_start.isoformat(),
                "anomaly_end": self.anomaly_end.isoformat(),
                "wage_day": self.wage_day.isoformat() if self.wage_day else None,
                "dry_days": [d.isoformat() for d in self.dry_days]}

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "Story":
        wage = raw.get("wage_day")
        return cls(anchor=datetime.fromisoformat(raw["anchor"]),
                   stockout_at=datetime.fromisoformat(raw["stockout_at"]),
                   refill_cash=float(raw["refill_cash"]),
                   anomaly_start=datetime.fromisoformat(raw["anomaly_start"]),
                   anomaly_end=datetime.fromisoformat(raw["anomaly_end"]),
                   wage_day=date.fromisoformat(wage) if wage else None,
                   dry_days=tuple(date.fromisoformat(d) for d in raw.get("dry_days", [])))


def candidates(anchor: datetime) -> list[datetime]:
    """Stock-out times to try, earliest first: STOCKOUT_LOCAL today/tomorrow/after, far enough."""
    day = anchor.astimezone(BDT).date()
    out = []
    for k in range(CANDIDATE_DAYS):
        at = datetime.combine(day + timedelta(days=k), STOCKOUT_LOCAL, tzinfo=BDT)
        if at - anchor >= timedelta(hours=MIN_LEAD_H):
            out.append(at)
    return out
