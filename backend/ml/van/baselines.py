"""Evaluation policies on one van instance (same stops, matrix and config for all):
A separate trip per agent, B nearest-neighbour, C OR-Tools with hard deadlines, D the full model
(OR-Tools, soft deadlines, BDT objective, fairness guard, seeded near-optimal order).
The routing itself lives in app/rules/van_routing. `seed` only matters to D.
"""

import time
from collections.abc import Callable, Sequence

from app.rules.van_routing import heuristics, solver
from app.rules.van_routing.matrix import Matrix
from app.rules.van_routing.models import Solution, Stop, VanConfig

Policy = Callable[[Sequence[Stop], Matrix, VanConfig, int], Solution]


def separate_trips(stops: Sequence[Stop], m: Matrix, cfg: VanConfig, seed: int = 0) -> Solution:
    t0 = time.perf_counter()
    seqs, dropped = heuristics.separate_trips(stops, m, cfg)
    return solver.finish(seqs, dropped, stops, m, cfg, "soft", "separate_trips", "heuristic", t0)


def nearest_neighbour(stops: Sequence[Stop], m: Matrix, cfg: VanConfig,
                      seed: int = 0) -> Solution:
    t0 = time.perf_counter()
    seqs, dropped = heuristics.nearest_neighbour(stops, m, cfg)
    return solver.finish(seqs, dropped, stops, m, cfg, "soft", "nearest_neighbour", "heuristic",
                         t0)


def hard_deadline(stops: Sequence[Stop], m: Matrix, cfg: VanConfig, seed: int = 0) -> Solution:
    return solver.solve(stops, m, cfg, mode="hard")


def full_model(stops: Sequence[Stop], m: Matrix, cfg: VanConfig, seed: int = 0) -> Solution:
    return solver.plan(stops, m, cfg, seed)


POLICIES: dict[str, Policy] = {"A_separate_trips": separate_trips,
                               "B_nearest_neighbour": nearest_neighbour,
                               "C_hard_deadline": hard_deadline, "D_full_model": full_model}
