"""Safety: the per-van cash cap is a hard load limit (VanConfig.load_cap_bdt); and the stop order
is a seeded pick among near-optimal orders, so a van carrying cash does not follow a fully
predictable route.

Candidates are the plan itself, each route reversed, and each route with two neighbouring stops
swapped. Every feasible candidate within near_optimal_pct of the best candidate's cost (van cost
plus lateness) may be picked. The same seed always picks the same order.
"""

import random
from collections.abc import Iterator, Sequence

from app.rules.van_routing.cost import EPS, evaluate, fits, route_total
from app.rules.van_routing.matrix import Matrix
from app.rules.van_routing.models import Stop, VanConfig

Seqs = list[list[int]]


def _variants(seqs: Seqs) -> Iterator[Seqs]:
    yield seqs
    for r, seq in enumerate(seqs):
        if len(seq) < 2:
            continue
        orders = [seq[::-1]] + [[*seq[:k], seq[k + 1], seq[k], *seq[k + 2:]]
                                for k in range(len(seq) - 1)]
        for order in orders:
            yield [*seqs[:r], order, *seqs[r + 1:]]


def _cost(seqs: Seqs, stops: Sequence[Stop], m: Matrix, cfg: VanConfig) -> float | None:
    total = 0.0
    for seq in seqs:
        if not seq:
            continue
        route = evaluate(0, seq, stops, m, cfg)
        if not fits(route, cfg):
            return None
        total += route_total(route)
    return total


def near_optimal(seqs: Seqs, stops: Sequence[Stop], m: Matrix, cfg: VanConfig,
                 seed: int) -> tuple[Seqs, str]:
    """(chosen routes, "k/n"): pick k (1-based) of n orders within the cost tolerance."""
    seen: set[tuple[tuple[int, ...], ...]] = set()
    pool: list[tuple[float, Seqs]] = []
    for cand in _variants(seqs):
        key = tuple(tuple(s) for s in cand)
        if key in seen:
            continue
        seen.add(key)
        cost = _cost(cand, stops, m, cfg)
        if cost is not None:
            pool.append((cost, cand))
    if not pool:
        return seqs, "1/1"
    best = min(c for c, _ in pool)
    near = [s for c, s in pool if c <= best * (1 + cfg.near_optimal_pct) + EPS]
    k = random.Random(seed).randrange(len(near))
    return [list(s) for s in near[k]], f"{k + 1}/{len(near)}"
