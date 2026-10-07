"""Calendar and weather for ANY day (live clock). Same rules as the fixed timeline
(calendar_effects.py, demand.py, weather.py), but per calendar date instead of per window index,
with holidays from data/holidays_bd.yaml and weather for all twelve months.

The fixed-timeline modules are left untouched on purpose: fixed mode must reproduce the
benchmark data bit for bit. Every number is a synthetic assumption (docs/SYNTHETIC_ASSUMPTIONS.md).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

import numpy as np
import yaml

from app.core.config import BACKEND_DIR
from app.models.enums import UrbanRural
from ml.data_gen import calendar_effects as cal
from ml.data_gen import demand as dem
from ml.data_gen.geography import DISTRICTS, HAT_WEEKDAY, RAIN_FACTOR
from ml.data_gen.timeline import FRI, START, THU
from ml.data_gen.weather import RAIN_CAP_MM, RAIN_DROP, SEVERE_RAIN_MM

HOLIDAYS_FILE = BACKEND_DIR / "data" / "holidays_bd.yaml"
EPOCH = START.date()  # demand trend anchor: the fixed timeline's first day
U, P, R = UrbanRural.urban, UrbanRural.peri_urban, UrbanRural.rural

# Months 1-5 are the fixed timeline's values; 6-12 add the monsoon and the dry winter.
RAIN_PROB: dict[int, float] = {1: 0.03, 2: 0.05, 3: 0.10, 4: 0.25, 5: 0.40, 6: 0.55, 7: 0.65,
                               8: 0.60, 9: 0.50, 10: 0.25, 11: 0.06, 12: 0.03}
# Gamma scale (mm) of a wet day's rain; the monsoon rains more often, not much harder, than May.
RAIN_SCALE: dict[int, float] = {m: 8.0 + 6.0 * m for m in range(1, 6)} | {
    6: 30.0, 7: 32.0, 8: 30.0, 9: 28.0, 10: 22.0, 11: 14.0, 12: 12.0}
MEAN_TEMP: dict[int, float] = {1: 18.5, 2: 22.0, 3: 26.5, 4: 28.5, 5: 29.5, 6: 29.5, 7: 29.0,
                               8: 29.2, 9: 29.0, 10: 27.5, 11: 24.0, 12: 20.0}


@dataclass(frozen=True)
class Holiday:
    day: date
    kind: str  # "holiday" | "eid"
    status: str  # "fixed_date" | "unverified"
    name_en: str
    name_bn: str


@cache
def load_holidays(path: Path = HOLIDAYS_FILE) -> tuple[Holiday, ...]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = [Holiday(day=r["date"], kind=str(r["kind"]), status=str(r["status"]),
                   name_en=str(r["name_en"]), name_bn=str(r["name_bn"]))
           for r in raw.get("holidays", [])]
    for h in out:
        if not isinstance(h.day, date) or h.kind not in ("holiday", "eid"):
            raise ValueError(f"bad holiday row in {path.name}: {h}")
    return tuple(sorted(out, key=lambda h: h.day))


def eid_offset(d: date, holidays: Iterable[Holiday]) -> int | None:
    """Days from the nearest Eid whose rush/holiday window (EID_OFFSETS) covers d."""
    for h in holidays:
        k = (d - h.day).days
        if h.kind == "eid" and k in cal.EID_OFFSETS:
            return k
    return None


def is_holiday(d: date, holidays: Iterable[Holiday]) -> bool:
    return any(h.kind == "holiday" and h.day == d for h in holidays)


def bank_closed(d: date, holidays: tuple[Holiday, ...]) -> bool:
    k = eid_offset(d, holidays)
    return (k is not None and k in cal.EID_BANK_CLOSED) or is_holiday(d, holidays)


def eid_stock_up(d: date, holidays: tuple[Holiday, ...]) -> float:
    """Agents hold more cash in the pre-Eid rush (simulate.EID_STOCK_UP)."""
    from ml.data_gen.simulate import EID_STOCK_UP, EID_STOCK_UP_MULT

    k = eid_offset(d, holidays)
    return EID_STOCK_UP_MULT if k is not None and k in EID_STOCK_UP else 1.0


def day_multipliers(area: UrbanRural, district: str, d: date, holidays: tuple[Holiday, ...],
                    wage_district_days: frozenset[tuple[str, date]] = frozenset()
                    ) -> tuple[float, float]:
    """(cash_out, cash_in) multiplier of one day: salary, factory wages, Eid, holidays.
    wage_district_days: extra factory wage days (the labelled demo event)."""
    out = inn = 1.0
    if d.day <= 3:
        out *= cal.SALARY_OUT[area][d.day - 1]
        inn *= cal.SALARY_IN[area][d.day - 1]
    wage = d.day in cal.GARMENT_DAYS and district in cal.GARMENT_DISTRICTS
    if (wage or (district, d) in wage_district_days) and area is not R:
        out *= cal.GARMENT_OUT
        inn *= cal.GARMENT_IN
    k = eid_offset(d, holidays)
    if k is not None:
        i = k - cal.EID_OFFSETS[0]
        out *= float(cal._eid_table(cal.EID_OUT, area)[i])
        inn *= float(cal._eid_table(cal.EID_IN, area)[i])
    if is_holiday(d, holidays):
        out *= cal.HOLIDAY_MULT[area]
        inn *= cal.HOLIDAY_MULT[area]
    return out, inn


def _hat(area: UrbanRural, district: str, d: date) -> tuple[np.ndarray, np.ndarray]:
    out, inn = np.ones(24), np.ones(24)
    wd = HAT_WEEKDAY.get(district)
    if wd is None or area is U:
        return out, inn
    hours = np.arange(24)
    if d.weekday() == wd:
        mask = np.isin(hours, list(cal.HAT_HOURS))
        out[mask] *= cal.HAT_OUT[area]
        inn[mask] *= cal.HAT_IN[area]
    if d.weekday() == (wd - 1) % 7:
        out[hours >= 16] *= cal.HAT_EVE_OUT
    return out, inn


def hourly_calendar(area: UrbanRural, district: str, d: date, holidays: tuple[Holiday, ...],
                    wage_district_days: frozenset[tuple[str, date]] = frozenset()
                    ) -> tuple[np.ndarray, np.ndarray]:
    """(out, in) multipliers of the 24 hours of day d (demand._calendar for one day)."""
    wd = d.weekday()
    base = dem.hour_share(area) * dem.WEEKDAY_MULT[area][wd]
    if wd == FRI:
        base[list(dem.JUMUAH_HOURS)] *= dem.JUMUAH_MULT
    base = base * (1.0 + dem.TREND_PER_DAY * (d - EPOCH).days)
    d_out, d_in = day_multipliers(area, district, d, holidays, wage_district_days)
    h_out, h_in = _hat(area, district, d)
    thu_in = dem.THURSDAY_IN_EXTRA[area] if wd == THU else 1.0
    return base * d_out * h_out, base * d_in * h_in * thu_in


def rain_multiplier(rain_mm: float, area: UrbanRural) -> float:
    return 1.0 - RAIN_DROP[area] * min(rain_mm, RAIN_CAP_MM) / RAIN_CAP_MM


def weather_of_day(seed: int, d: date, dry: frozenset[tuple[str, date]] = frozenset()
                   ) -> dict[str, tuple[float, float, bool]]:
    """district -> (rain_mm, temp_c, severe) for day d; the same date always gives the same."""
    rng = np.random.default_rng([seed, 5, d.toordinal()])
    out: dict[str, tuple[float, float, bool]] = {}
    for district in DISTRICTS:  # fixed order: each district always gets the same draws
        f = RAIN_FACTOR[district]
        wet = rng.random() < min(RAIN_PROB[d.month] * f, 0.9)
        amount = float(rng.gamma(shape=0.9, scale=RAIN_SCALE[d.month] * f))
        noise = float(rng.normal(0.0, 1.5))
        rain = 0.0 if (district, d) in dry else round(amount if wet else 0.0, 1)
        temp = round(MEAN_TEMP[d.month] + noise - (3.0 if rain > 5 else 0.0), 1)
        out[district] = (rain, temp, rain >= SEVERE_RAIN_MM)
    return out
