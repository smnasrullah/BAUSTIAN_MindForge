"""Seeded synthetic van instances for the pure rules tests (no database)."""

import numpy as np

from app.rules.van_routing import matrix
from app.rules.van_routing.matrix import Matrix, Point
from app.rules.van_routing.models import Stop, VanConfig

DEPOT = Point("depot:TEST", 23.80, 90.40)


def stops(n: int, seed: int = 7, amount: tuple[float, float] = (20_000, 150_000),
          deadline: tuple[float, float] = (1.0, 8.0),
          lost: tuple[float, float] = (500, 4_000)) -> list[Stop]:
    rng = np.random.default_rng(seed)
    return [Stop(agent_id=i + 1, lat=DEPOT.lat + float(rng.uniform(-0.08, 0.08)),
                 lng=DEPOT.lng + float(rng.uniform(-0.08, 0.08)),
                 amount_bdt=round(float(rng.uniform(*amount)), -2),
                 deadline_h=float(rng.uniform(*deadline)), lost_per_h_bdt=float(rng.uniform(*lost)))
            for i in range(n)]


def points(s: list[Stop]) -> list[Point]:
    return [DEPOT] + [Point(f"agent:{x.agent_id}", x.lat, x.lng) for x in s]


def estimate(s: list[Stop], cfg: VanConfig) -> Matrix:
    return matrix.build(points(s), {}, cfg)
