"""Stability: distributor pins (lock / include / exclude) and the freeze window.

- lock: the stop stays on its van and must be served.
- include: the stop must be served (any van).
- exclude: the stop is left out of the plan (drop reason `excluded`).
- frozen: a stop of the approved plan whose van arrives within the freeze window keeps its van
  and is served; it overrides any pin.
"Must be served" is a very high drop price in the search, so a stop no van can take is still
dropped, with reason `capacity`. Re-planning happens only when the input hash changes.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal

from app.rules.van_routing.models import Stop

Action = Literal["lock", "include", "exclude"]


@dataclass(frozen=True)
class Pin:
    action: Action
    vehicle_no: int | None = None  # lock only


@dataclass(frozen=True)
class Applied:
    stops: list[Stop]  # what the optimizer routes
    index: list[int]  # input index of each routed stop
    excluded: list[int]  # input indices left out by the distributor
    frozen: list[int]  # input indices kept on their van by the freeze window


def frozen(planned: Sequence[tuple[int, int, float]], freeze_h: float) -> dict[int, int]:
    """(agent id, van number, hours until its ETA) of an approved plan's open stops ->
    agent id -> van number for the stops the van reaches within the freeze window."""
    return {agent: van for agent, van, eta_h in planned if 0 < eta_h <= freeze_h}


def apply(stops: Sequence[Stop], pins: Mapping[int, Pin], frozen_vans: Mapping[int, int],
          vehicles: int) -> Applied:
    """Pins and frozen stops are keyed by agent id. A van number beyond today's fleet keeps only
    the must-serve part."""
    out: list[Stop] = []
    index: list[int] = []
    excluded: list[int] = []
    kept: list[int] = []
    for i, s in enumerate(stops):
        van = frozen_vans.get(s.agent_id)
        pin = pins.get(s.agent_id)
        if van is None and pin is not None and pin.action == "exclude":
            excluded.append(i)
            continue
        if van is not None:
            kept.append(i)
        elif pin is not None and pin.action == "lock":
            van = pin.vehicle_no
        if van is not None or pin is not None:
            s = replace(s, must_serve=True,
                        vehicle=van if van is not None and 1 <= van <= vehicles else None)
        out.append(s)
        index.append(i)
    return Applied(out, index, excluded, kept)
