"""Road cache (backend/data/road_cache/*.json, built offline by scripts/build_road_cache.py).

Read once per process; never calls the internet. A pair missing here is estimated by
app/rules/van_routing/matrix.py (haversine x road factor) and labelled `estimate`.
File: {"version", "source", "built_at", "legs": {"<from>|<to>": [km, minutes]},
"polylines": {"<from>|<to>": "<encoded polyline>"}}.
"""

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.config import BACKEND_DIR

CACHE_DIR = BACKEND_DIR / "data" / "road_cache"
Pair = tuple[str, str]


@dataclass(frozen=True)
class RoadCacheData:
    legs: dict[Pair, tuple[float, float]]
    polylines: dict[Pair, str]
    version: str  # content hash; part of the plan input hash


def depot_key(distributor_code: str) -> str:
    return f"depot:{distributor_code}"


def agent_key(agent_code: str) -> str:
    return f"agent:{agent_code}"


def _pair(raw: str) -> Pair:
    a, _, b = raw.partition("|")
    return a, b


def read(directory: Path) -> RoadCacheData:
    legs: dict[Pair, tuple[float, float]] = {}
    polylines: dict[Pair, str] = {}
    digest = hashlib.sha256()
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        raw = path.read_bytes()
        digest.update(path.name.encode() + raw)
        doc = json.loads(raw)
        for key, (km, minutes) in doc.get("legs", {}).items():
            legs[_pair(key)] = (float(km), float(minutes))
        for key, line in doc.get("polylines", {}).items():
            polylines[_pair(key)] = str(line)
    return RoadCacheData(legs, polylines, digest.hexdigest()[:16] if legs else "none")


@lru_cache(maxsize=1)
def load() -> RoadCacheData:
    return read(CACHE_DIR)
