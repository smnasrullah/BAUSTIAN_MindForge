// Shared fixtures for the distributor page tests (shapes follow the OpenAPI schema).
import type {
  AgentSummary,
  AgentRiskPage,
  AgentRiskRow,
  AnomalyDetail,
  AnomalyItem,
  LlmText,
  RequestItem,
  SwapItem,
  SwapPage,
} from "../../api/types";

export const AS_OF = "2026-03-10T06:00:00Z";
export const MODEL = "lgbm-q-2026.03";

export function riskRow(over: Partial<AgentRiskRow>): AgentRiskRow {
  return {
    agent_id: 1,
    code: "A001",
    name: "Karim Telecom",
    district: "Dhaka",
    upazila: "Savar",
    tier: 2,
    urban_rural: "urban",
    lat: 23.85,
    lng: 90.26,
    level: "red",
    probability: 0.82,
    hours_to_stockout: 5.5,
    stockout_at: "2026-03-10T11:30:00Z",
    worst_float: "cash",
    ...over,
  };
}

export function riskPage(items: AgentRiskRow[], over: Partial<AgentRiskPage> = {}): AgentRiskPage {
  return { items, total: items.length, page: 1, page_size: 20, horizon_h: 24, model_version: MODEL, as_of: AS_OF, generated_at: AS_OF, ...over };
}

export function swapItem(over: Partial<SwapItem>): SwapItem {
  return {
    id: 7,
    amount_bdt: 25000,
    distance_km: 1.8,
    float_type: "cash",
    status: "pending",
    score: 0.91,
    van_trip_saved: true,
    note: null,
    deadline_at: null,
    decided_at: null,
    generated_at: AS_OF,
    model_version: MODEL,
    donor: { agent_id: 1, code: "A001", name: "Karim Telecom", upazila: "Savar", response: "accepted" },
    receiver: { agent_id: 2, code: "A002", name: "Rahim Store", upazila: "Savar", response: null },
    ...over,
  };
}

export function swapPage(items: SwapItem[]): SwapPage {
  return { items, total: items.length, page: 1, page_size: 100, advisory: true, van_trips_avoided: items.filter((s) => s.van_trip_saved).length };
}

export function requestItem(over: Partial<RequestItem>): RequestItem {
  return {
    id: 1,
    advisory: true,
    agent: { agent_id: 1, code: "A001", name: "Karim Telecom" },
    amount_bdt: 40000,
    channel: null,
    created_at: AS_OF,
    deadline_at: "2026-03-10T10:00:00Z",
    decided_at: null,
    decided_by: null,
    float_type: "cash",
    note: null,
    recommendation_id: 11,
    requested_by: "agent1",
    status: "requested",
    ...over,
  };
}

export function anomalyItem(over: Partial<AnomalyItem>): AnomalyItem {
  return {
    id: 3,
    agent: { agent_id: 1, code: "A001", name: "Karim Telecom", district: "Dhaka", upazila: "Savar" },
    generated_at: AS_OF,
    model_version: "iforest-2026.03",
    note: null,
    peer_group: "urban · tier 2",
    reasons: [{ feature: "cash_out_growth", direction: "high", value: 2.4, peer_median: 1.1, deviation: 3.2 }],
    reviewed_at: null,
    score: 0.71,
    status: "open",
    threshold: 0.6,
    window_start: "2026-03-09T06:00:00Z",
    window_end: AS_OF,
    ...over,
  };
}

export function anomalyDetail(over: Partial<AnomalyDetail> = {}): AnomalyDetail {
  const { reasons, ...item } = anomalyItem({});
  return {
    ...item,
    reasons,
    advisory: true,
    context: { cash_in_bdt: 120000, cash_out_bdt: 310000, baseline_cash_out_bdt: 140000, refills: 4 },
    features: [
      { name: "cash_out_growth", value: 2.4, p10: 0.7, p25: 0.9, p50: 1.1, p75: 1.3, p90: 1.6, percentile: 0.99, deviation: 3.2 },
      { name: "refills_per_day", value: 2, p10: 0.5, p25: 1, p50: 1.2, p75: 1.6, p90: 2.4, percentile: 0.82, deviation: 1.1 },
    ],
    history_h: 168,
    peer_count: 38,
    peer_scores: { p50: 0.32, p90: 0.55, max: 0.71 },
    window_h: 24,
    reviewed_by: null,
    ...over,
  };
}

export function llmText(over: Partial<LlmText> = {}): LlmText {
  return {
    advisory: true,
    cached: false,
    cited_factors: ["cash_out_growth"],
    evidence_hash: "abc123",
    fallback_reason: null,
    generated_at: AS_OF,
    generated_by: "llm",
    no_api_key: false,
    guard_result: "pass",
    intent: "distributor_briefing",
    lang: "en",
    model: "claude-haiku-4-5-20251001",
    model_version: MODEL,
    provider: "anthropic",
    template_text: "Template: 3 agents need cash today.",
    text: "Three agents may run short of cash today; Karim Telecom first.",
    ...over,
  };
}

export function agentSummary(): AgentSummary {
  return {
    agent_id: 1,
    as_of: AS_OF,
    generated_at: AS_OF,
    model_version: MODEL,
    unit: "BDT",
    level: "red",
    agent: {
      id: 1,
      code: "A001",
      name: "Karim Telecom",
      distributor_id: 1,
      district: "Dhaka",
      upazila: "Savar",
      region: "Dhaka Division",
      tier: 2,
      urban_rural: "urban",
      lat: 23.85,
      lng: 90.26,
      is_active: true,
      opened_on: null,
      cash_capacity: 300000,
      emoney_capacity: 300000,
    },
    by_horizon: [
      { horizon_h: 6, level: "amber", probability: 0.31 },
      { horizon_h: 24, level: "red", probability: 0.82 },
      { horizon_h: 72, level: "red", probability: 0.93 },
    ],
    floats: [],
  };
}
