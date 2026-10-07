// Synthetic van plans for the vanRoutes tests. Coordinates are around the Dhaka depot.
import type { VanLeg, VanNarrative, VanPlan, VanPlanPage, VanPlanSummary, VanRoute, VanStop } from "../../../api/vanPlans";

export function vanStop(over: Partial<VanStop> = {}): VanStop {
  return {
    id: 1,
    seq: 1,
    agent_id: 11,
    agent_code: "AGT-0011",
    agent_name: "Rahim Telecom",
    lat: 23.81,
    lng: 90.41,
    group: "urban/tier1",
    amount_bdt: 120_000,
    source_quantile: "q90",
    eta_lo: "2026-03-10T06:00:00Z",
    eta_hi: "2026-03-10T06:20:00Z",
    deadline: "2026-03-10T09:00:00Z",
    late_h: null,
    penalty_bdt: 0,
    lost_per_h_bdt: 900,
    stockout_before_arrival_p: null,
    status: "planned",
    reason: null,
    delivered_at: null,
    delivered_amount_bdt: null,
    ...over,
  };
}

export function vanLeg(over: Partial<VanLeg> = {}): VanLeg {
  return { from_key: "depot:DST-DHK", to_key: "agent:AGT-0011", km: 4.2, minutes: 14, source: "road_cache", polyline: null, ...over };
}

export function vanRoute(over: Partial<VanRoute> = {}): VanRoute {
  return {
    id: 101,
    vehicle_no: 1,
    km: 11.5,
    minutes: 52,
    cash_load_bdt: 310_000,
    cost_bdt: 3_400,
    legs: [
      vanLeg(),
      vanLeg({ from_key: "agent:AGT-0011", to_key: "agent:AGT-0012", km: 3.1, minutes: 11 }),
      vanLeg({ from_key: "agent:AGT-0012", to_key: "depot:DST-DHK", km: 4.2, minutes: 15 }),
    ],
    stops: [
      vanStop(),
      vanStop({ id: 2, seq: 2, agent_id: 12, agent_code: "AGT-0012", agent_name: "Salma Store", lat: 23.83, lng: 90.43, group: "urban/tier2", amount_bdt: 190_000, late_h: 0.5, penalty_bdt: 450 }),
    ],
    ...over,
  };
}

export function vanPlan(over: Partial<VanPlan> = {}): VanPlan {
  const second = vanRoute({
    id: 102,
    vehicle_no: 2,
    km: 20,
    minutes: 70,
    cash_load_bdt: 90_000,
    cost_bdt: 4_100,
    legs: [vanLeg({ to_key: "agent:AGT-0013", km: 10, minutes: 35 }), vanLeg({ from_key: "agent:AGT-0013", to_key: "depot:DST-DHK", km: 10, minutes: 35 })],
    stops: [vanStop({ id: 3, seq: 1, agent_id: 13, agent_code: "AGT-0013", agent_name: "Bilkis Agent Point", lat: 23.72, lng: 90.36, group: "rural/tier3", amount_bdt: 90_000 })],
  });
  return {
    id: 7,
    distributor_id: 1,
    status: "pending",
    planned_at: "2026-03-10T05:00:00Z",
    clock_origin: "2026-03-10T05:00:00Z",
    horizon_h: 24,
    solver: "ortools",
    stopped_by: "solution_limit",
    solve_ms: 480,
    distance_source: "road_cache",
    model_version: "forecast-v3",
    generated_at: "2026-03-10T05:00:01Z",
    input_hash: "abc123",
    served: 3,
    dropped: 2,
    trips: 2,
    km: 31.5,
    total_bdt: 9_800,
    advisory: true,
    reused: false,
    params: { config: { vehicles: 2, capacity_bdt: 1_500_000, cash_cap_bdt: 1_500_000 }, rules: "v1" },
    objective: {
      van_fixed_bdt: 3_000,
      van_km_bdt: 790,
      van_time_bdt: 410,
      late_penalty_bdt: 450,
      skip_penalty_bdt: 5_150,
      van_bdt: 4_200,
      total_bdt: 9_800,
    },
    separate_trips: { km: 58, trips: 3, van_bdt: 7_600, total_bdt: 12_300 },
    depot: { code: "DST-DHK", name: "Dhaka depot", lat: 23.78, lng: 90.4 },
    routes: [vanRoute(), second],
    unrouted: [
      vanStop({ id: 4, seq: null, agent_id: 14, agent_code: "AGT-0014", agent_name: "Karim Pharmacy", lat: 23.9, lng: 90.5, group: "rural/tier3", amount_bdt: 40_000, eta_lo: null, eta_hi: null, status: "dropped", reason: "swap_suggested" }),
      vanStop({ id: 5, seq: null, agent_id: 15, agent_code: "AGT-0015", agent_name: "Nasima Corner", lat: 23.95, lng: 90.2, group: "rural/tier3", amount_bdt: 15_000, eta_lo: null, eta_hi: null, status: "dropped", reason: "cost_gt_value" }),
    ],
    decided_by: null,
    decided_at: null,
    note: null,
    ...over,
  };
}

export function vanSummary(plan: VanPlan = vanPlan()): VanPlanSummary {
  return {
    id: plan.id,
    distributor_id: plan.distributor_id,
    status: plan.status,
    planned_at: plan.planned_at,
    clock_origin: plan.clock_origin,
    horizon_h: plan.horizon_h,
    solver: plan.solver,
    stopped_by: plan.stopped_by,
    solve_ms: plan.solve_ms,
    distance_source: plan.distance_source,
    model_version: plan.model_version,
    generated_at: plan.generated_at,
    input_hash: plan.input_hash,
    served: plan.served,
    dropped: plan.dropped,
    trips: plan.trips,
    km: plan.km,
    total_bdt: plan.total_bdt,
    advisory: plan.advisory,
  };
}

export function vanPage(plans: VanPlan[]): VanPlanPage {
  return { items: plans.map((p) => vanSummary(p)), total: plans.length, page: 1, page_size: 20 };
}

export function vanNarrative(over: Partial<VanNarrative> = {}): VanNarrative {
  return {
    plan_id: 7,
    lang: "en",
    text: "Van 1 serves two shops first because their cash runs out soonest.",
    generated_by: "template",
    model_version: "forecast-v3",
    generated_at: "2026-03-10T05:00:02Z",
    distance_source: "road_cache",
    ...over,
  };
}
