import { describe, expect, it } from "vitest";

import { routeColor, routeVar } from "./routePalette";
import { vanLeg, vanPlan, vanRoute, vanStop } from "./testFixtures";
import {
  allStops,
  findStop,
  savingsHeadline,
  stopHealth,
  controlsOf,
  decodePolyline,
  groupRows,
  hasApproxLegs,
  lateHours,
  loadLimit,
  parseGroup,
  planBounds,
  routeLines,
  sameControls,
  savingsRows,
  spokeLines,
  stopMarkers,
} from "./vanRoutesModel";

const PALETTE = ["#111111", "#222222", "#333333"];

describe("decodePolyline", () => {
  it("decodes the reference polyline to [lng, lat] pairs", () => {
    expect(decodePolyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")).toEqual([
      [-120.2, 38.5],
      [-120.95, 40.7],
      [-126.453, 43.252],
    ]);
  });

  it("returns nothing for an empty string", () => {
    expect(decodePolyline("")).toEqual([]);
  });
});

describe("routes and spokes", () => {
  it("draws one line per leg in the van colour, straight when there is no road polyline", () => {
    const lines = routeLines(vanPlan(), PALETTE);
    expect(lines.features).toHaveLength(5);
    const first = lines.features[0];
    expect(first?.properties).toEqual({ vehicle: 1, color: "#111111", approx: true });
    expect(first?.geometry.coordinates).toEqual([
      [90.4, 23.78],
      [90.41, 23.81],
    ]);
    expect(lines.features.at(-1)?.properties.color).toBe("#222222");
  });

  it("uses the road polyline when a leg has one", () => {
    const plan = vanPlan({ routes: [vanRoute({ legs: [vanLeg({ polyline: "_p~iF~ps|U_ulLnnqC_mqNvxq`@" })] })] });
    expect(routeLines(plan, PALETTE).features[0]?.geometry.coordinates).toHaveLength(3);
    expect(routeLines(plan, PALETTE).features[0]?.properties.approx).toBe(false);
    expect(hasApproxLegs(plan)).toBe(false);
  });

  it("flags straight-line fallback legs as approximate", () => {
    expect(hasApproxLegs(vanPlan())).toBe(true);
  });

  it("skips a leg whose endpoint is unknown", () => {
    const plan = vanPlan({ routes: [vanRoute({ legs: [vanLeg({ to_key: "agent:UNKNOWN" })] })] });
    expect(routeLines(plan, PALETTE).features).toHaveLength(0);
  });

  it("draws one depot-to-agent spoke per served stop, none for skipped ones", () => {
    const spokes = spokeLines(vanPlan());
    expect(spokes.features).toHaveLength(3);
    expect(spokes.features[0]?.geometry.coordinates[0]).toEqual([90.4, 23.78]);
  });
});

describe("stops and bounds", () => {
  it("lists every stop, flagging the skipped ones", () => {
    const markers = stopMarkers(vanPlan());
    expect(markers).toHaveLength(5);
    expect(markers.filter((m) => m.dropped).map((m) => m.agentCode)).toEqual(["AGT-0014", "AGT-0015"]);
    expect(markers[0]).toMatchObject({ vehicle: 1, seq: 1 });
    expect(allStops(vanPlan())).toHaveLength(5);
  });

  it("frames the depot and all stops", () => {
    expect(planBounds(vanPlan())).toEqual([
      [90.2, 23.72],
      [90.5, 23.95],
    ]);
  });
});

describe("savings", () => {
  it("compares the plan with separate trips on the same inputs", () => {
    const rows = Object.fromEntries(savingsRows(vanPlan()).map((r) => [r.key, r]));
    expect(rows["km"]).toMatchObject({ before: 58, after: 31.5 });
    expect(rows["km"]?.delta).toBeCloseTo(-26.5);
    expect(rows["trips"]).toMatchObject({ before: 3, after: 2, delta: -1 });
    expect(rows["totalBdt"]).toMatchObject({ before: 12_300, after: 9_800, delta: -2_500 });
  });

  it("derives lost value as total minus van cost, so a worse row is visible", () => {
    const lost = savingsRows(vanPlan()).find((r) => r.key === "lostBdt");
    expect(lost).toMatchObject({ before: 4_700, after: 5_600, delta: 900 });
  });

  it("sums the hours that planned stops arrive late", () => {
    expect(lateHours(vanPlan())).toEqual({ hours: 0.5, stops: 1 });
  });
});

describe("fairness groups", () => {
  it("counts van, swap and not-served agents per group", () => {
    const rows = groupRows(vanPlan());
    expect(rows.map((r) => r.group)).toEqual(["rural/tier3", "urban/tier1", "urban/tier2"]);
    expect(rows[0]).toMatchObject({ total: 3, van: 1, swap: 1, notServed: 1 });
    expect(rows[0]?.covered).toBeCloseTo(2 / 3);
    expect(rows[2]?.maxLateH).toBe(0.5);
  });

  it("parses the group text and keeps anything else raw", () => {
    expect(parseGroup("rural/tier3")).toEqual({ area: "rural", tier: 3 });
    expect(parseGroup("urban/tier1")).toEqual({ area: "urban", tier: 1 });
    expect(parseGroup("hill")).toBeNull();
  });
});

describe("controls", () => {
  it("reads the controls back from the solved plan", () => {
    expect(controlsOf(vanPlan())).toEqual({ vehicles: 2, capacityBdt: 1_500_000, cashCapBdt: 1_500_000 });
  });

  it("falls back to the route count and defaults when params carry no config", () => {
    expect(controlsOf(vanPlan({ params: {} }))).toEqual({ vehicles: 2, capacityBdt: 1_500_000, cashCapBdt: 1_500_000 });
  });

  it("compares controls and takes the smaller of capacity and cash cap as the load limit", () => {
    const a = { vehicles: 2, capacityBdt: 900_000, cashCapBdt: 600_000 };
    expect(sameControls(a, { ...a })).toBe(true);
    expect(sameControls(a, { ...a, vehicles: 3 })).toBe(false);
    expect(loadLimit(a)).toBe(600_000);
  });
});

describe("route palette", () => {
  it("wraps around when there are more vans than colours", () => {
    expect(routeColor(PALETTE, 1)).toBe("#111111");
    expect(routeColor(PALETTE, 4)).toBe("#111111");
    expect(routeColor([], 1)).toMatch(/^rgb/);
    expect(routeVar(1)).toBe("var(--route-1)");
    expect(routeVar(7)).toBe("var(--route-1)");
  });

  it("marks a stop at risk when it is flagged or late, and gives skipped stops no status", () => {
    expect(stopHealth(vanStop())).toBe("ok");
    expect(stopHealth(vanStop({ late_h: 0 }))).toBe("ok");
    expect(stopHealth(vanStop({ late_h: 0.5 }))).toBe("risk");
    expect(stopHealth(vanStop({ stockout_risk_flag: true }))).toBe("risk");
    expect(stopHealth(vanStop({ status: "dropped", seq: null, stockout_risk_flag: true }))).toBeNull();
  });

  it("finds a stop with its van, a skipped one without, and nothing for an unknown id", () => {
    const plan = vanPlan();
    expect(findStop(plan, 3)).toMatchObject({ stop: { agent_code: "AGT-0013" }, vehicle: 2 });
    expect(findStop(plan, 4)).toMatchObject({ stop: { agent_code: "AGT-0014" }, vehicle: null });
    expect(findStop(plan, 99)).toBeNull();
    expect(findStop(plan, null)).toBeNull();
  });

  it("reports km and total cost saved against separate trips, and a loss as negative", () => {
    const head = savingsHeadline(vanPlan());
    expect(head.kmSaved).toBeCloseTo(26.5);
    expect(head.kmShare).toBeCloseTo(26.5 / 58);
    expect(head.bdtSaved).toBe(2_500);
    expect(head.bdtShare).toBeCloseTo(2_500 / 12_300);
    const plan = vanPlan();
    const worse = savingsHeadline(vanPlan({ objective: { ...plan.objective, total_bdt: 15_000 }, separate_trips: { ...plan.separate_trips, km: 0 } }));
    expect(worse.bdtSaved).toBe(-2_700);
    expect(worse.kmShare).toBe(0);
  });
});
