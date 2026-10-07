"""Simple routing: separate trips (policy A), nearest-neighbour (policy B), and the fallback when
OR-Tools is missing or finds nothing (nearest-neighbour + 2-opt + prune + repair).

Routes are lists of stop indices; ties break on the stop index so every result is deterministic.
"""

from collections.abc import Sequence

from app.rules.van_routing.cost import (
    EPS,
    cheapest_insertion,
    drop_cost,
    evaluate,
    fits,
    route_total,
)
from app.rules.van_routing.matrix import Matrix
from app.rules.van_routing.models import Stop, VanConfig, WindowMode

Seqs = list[list[int]]


def separate_trips(stops: Sequence[Stop], m: Matrix, cfg: VanConfig) -> tuple[Seqs, list[int]]:
    """Every agent gets its own depot -> agent -> depot trip, all leaving at once (no fleet limit:
    this is the 'one dispatch per agent' baseline). Only a trip that cannot fit is dropped."""
    seqs: Seqs = []
    dropped: list[int] = []
    for i in range(len(stops)):
        if fits(evaluate(0, [i], stops, m, cfg), cfg):
            seqs.append([i])
        else:
            dropped.append(i)
    return seqs, dropped


def nearest_neighbour(stops: Sequence[Stop], m: Matrix, cfg: VanConfig,
                      mode: WindowMode = "soft") -> tuple[Seqs, list[int]]:
    """Fill one van after the other with the nearest stop that still fits."""
    left = set(range(len(stops)))
    seqs: Seqs = []
    while left and len(seqs) < cfg.vehicles:
        seq: list[int] = []
        while True:
            last = seq[-1] + 1 if seq else 0
            van = len(seqs) + 1
            nxt = next((i for i in sorted(left, key=lambda i: (m.km[last][i + 1], i))
                        if stops[i].vehicle in (None, van)
                        and fits(evaluate(0, [*seq, i], stops, m, cfg), cfg, mode)), None)
            if nxt is None:
                break
            seq.append(nxt)
            left.remove(nxt)
        if not seq:
            break
        seqs.append(seq)
    return seqs, sorted(left)


def two_opt(seq: list[int], stops: Sequence[Stop], m: Matrix, cfg: VanConfig,
            mode: WindowMode = "soft") -> list[int]:
    """Reverse segments while that lowers the route's cost + lateness (first improvement)."""
    best, best_cost = seq, route_total(evaluate(0, seq, stops, m, cfg))
    improved = True
    while improved:
        improved = False
        for a in range(len(best) - 1):
            for b in range(a + 1, len(best)):
                cand = [*best[:a], *reversed(best[a:b + 1]), *best[b + 1:]]
                route = evaluate(0, cand, stops, m, cfg)
                if fits(route, cfg, mode) and route_total(route) < best_cost - EPS:
                    best, best_cost, improved = cand, route_total(route), True
    return best


def prune(seqs: Seqs, dropped: list[int], stops: Sequence[Stop], m: Matrix,
          cfg: VanConfig) -> None:
    """Drop the stop whose service costs most above its value, one at a time (in place).
    Emptied routes stay in place, so route index k is still van k + 1."""
    while True:
        worst: tuple[float, int, int] | None = None
        for r_idx, seq in enumerate(seqs):
            full = route_total(evaluate(0, seq, stops, m, cfg))
            for pos, i in enumerate(seq):
                rest = [*seq[:pos], *seq[pos + 1:]]
                saving = full - (route_total(evaluate(0, rest, stops, m, cfg)) if rest else 0.0)
                gain = saving - drop_cost(stops[i], cfg)
                if gain > EPS and (worst is None or gain > worst[0] + EPS):
                    worst = (gain, r_idx, pos)
        if worst is None:
            return
        _, r_idx, pos = worst
        dropped.append(seqs[r_idx].pop(pos))


def repair(seqs: Seqs, dropped: list[int], stops: Sequence[Stop], m: Matrix, cfg: VanConfig,
           mode: WindowMode = "soft") -> None:
    """Insert dropped stops (highest skip penalty first) where serving is cheaper than skipping;
    so no stop is left out that a single insertion would make worth serving (in place)."""
    changed = True
    while changed:
        changed = False
        for i in sorted(dropped, key=lambda i: (-drop_cost(stops[i], cfg), i)):
            ins = cheapest_insertion(i, seqs, stops, m, cfg, mode)
            if ins is None or ins[0] >= drop_cost(stops[i], cfg) - EPS:
                continue
            _, r_idx, pos = ins
            if r_idx == len(seqs):
                seqs.append([])
            seqs[r_idx].insert(pos, i)
            dropped.remove(i)
            changed = True
            break


def fallback(stops: Sequence[Stop], m: Matrix, cfg: VanConfig,
             mode: WindowMode = "soft") -> tuple[Seqs, list[int]]:
    seqs, dropped = nearest_neighbour(stops, m, cfg, mode)
    seqs = [two_opt(s, stops, m, cfg, mode) for s in seqs]
    seqs += [[] for _ in range(cfg.vehicles - len(seqs))]  # index k = van k + 1 (locked stops)
    if mode == "soft":
        prune(seqs, dropped, stops, m, cfg)
    return seqs, dropped
