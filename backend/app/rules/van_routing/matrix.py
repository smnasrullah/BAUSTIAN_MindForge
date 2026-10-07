"""Travel matrix: road cache first, haversine x road factor otherwise (labelled per leg).

Index 0 is the depot, index i + 1 is stop i. Minutes are multiplied by the slower of the two
endpoints' day factors (Eid, rain, hat-bazar), whatever the distance source.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.rules.swap_rules import haversine_km
from app.rules.van_routing.models import DistanceSource, VanConfig

# (from key, to key) -> (road km, free-flow minutes)
RoadCache = Mapping[tuple[str, str], tuple[float, float]]


@dataclass(frozen=True)
class Point:
    key: str  # road cache key, e.g. "depot:DST-DHK" or "agent:AGT-0001"
    lat: float
    lng: float
    time_factor: float = 1.0


@dataclass(frozen=True)
class Matrix:
    km: tuple[tuple[float, ...], ...]
    minutes: tuple[tuple[float, ...], ...]
    cached: tuple[tuple[bool, ...], ...]

    @property
    def size(self) -> int:
        return len(self.km)

    @property
    def estimated_legs(self) -> int:
        n = self.size
        return sum(1 for i in range(n) for j in range(n) if i != j and not self.cached[i][j])

    @property
    def source(self) -> DistanceSource:
        """road_cache only when every leg came from the cache."""
        return "estimate" if self.estimated_legs else "road_cache"


def _leg(a: Point, b: Point, cache: RoadCache, cfg: VanConfig) -> tuple[float, float, bool]:
    hit = cache.get((a.key, b.key))
    if hit is not None:
        km, minutes = hit
        cached = True
    else:
        km = haversine_km(a.lat, a.lng, b.lat, b.lng) * cfg.road_factor
        minutes = km / cfg.speed_kmh * 60
        cached = False
    return km, minutes * max(a.time_factor, b.time_factor), cached


def build(points: Sequence[Point], cache: RoadCache, cfg: VanConfig) -> Matrix:
    km: list[tuple[float, ...]] = []
    minutes: list[tuple[float, ...]] = []
    cached: list[tuple[bool, ...]] = []
    for i, a in enumerate(points):
        legs = [(0.0, 0.0, True) if i == j else _leg(a, b, cache, cfg)
                for j, b in enumerate(points)]
        km.append(tuple(x[0] for x in legs))
        minutes.append(tuple(x[1] for x in legs))
        cached.append(tuple(x[2] for x in legs))
    return Matrix(tuple(km), tuple(minutes), tuple(cached))
