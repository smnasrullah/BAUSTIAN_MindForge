// Typed API payloads for agent page tests. As-of 06:00 UTC = 12:00 PM in Dhaka.
import type {
  AgentExplanation,
  AgentRecommendation,
  AgentSummary,
  EventPage,
  FloatSummary,
  FloatType,
  HorizonRisk,
  LlmText,
  WhatIfOut,
  WhatIfScenario,
} from "../../api/types";

export const AS_OF = "2026-03-10T06:00:00Z";
/** 09:40 UTC = 3:40 PM Dhaka, 3h 40m after as-of. */
export const CASH_STOCKOUT = "2026-03-10T09:40:00Z";
const GENERATED = "2026-03-10T06:01:00Z";
const MODEL = "lgbm-q-2026.03";

export const HORIZONS: HorizonRisk[] = [
  { horizon_h: 6, probability: 0.82, level: "red", confidence: 0.82 },
  { horizon_h: 24, probability: 0.4, level: "amber", confidence: 0.6 },
  { horizon_h: 72, probability: 0.1, level: "green", confidence: 0.9 },
];

const CALM: HorizonRisk[] = [
  { horizon_h: 6, probability: 0.02, level: "green", confidence: 0.98 },
  { horizon_h: 24, probability: 0.05, level: "green", confidence: 0.95 },
  { horizon_h: 72, probability: 0.12, level: "green", confidence: 0.88 },
];

export const CASH: FloatSummary = {
  float_type: "cash",
  balance: 18_000,
  capacity: 150_000,
  stockout_at: CASH_STOCKOUT,
  hours_to_stockout: 3 + 40 / 60,
  confidence: 0.82,
  level: "red",
  horizons: HORIZONS,
};

export const EMONEY: FloatSummary = {
  float_type: "emoney",
  balance: 90_000,
  capacity: 120_000,
  stockout_at: null,
  hours_to_stockout: null,
  confidence: 0.88,
  level: "green",
  horizons: CALM,
};

export const SUMMARY: AgentSummary = {
  agent_id: 1,
  as_of: AS_OF,
  model_version: MODEL,
  generated_at: GENERATED,
  unit: "BDT",
  level: "red",
  by_horizon: [
    { horizon_h: 6, level: "red", probability: 0.82 },
    { horizon_h: 24, level: "amber", probability: 0.4 },
    { horizon_h: 72, level: "green", probability: 0.12 },
  ],
  floats: [EMONEY, CASH],
  agent: {
    id: 1,
    code: "AGT-0001",
    name: "Mirpur 10 Mobile Point",
    distributor_id: 1,
    region: "Dhaka",
    district: "Dhaka",
    upazila: "Mirpur",
    urban_rural: "urban",
    tier: 1,
    lat: 23.8,
    lng: 90.36,
    cash_capacity: 150_000,
    emoney_capacity: 120_000,
    opened_on: null,
    is_active: true,
  },
};

function scenario(f: FloatSummary): WhatIfScenario {
  const series = Array.from({ length: 73 }, (_, hour) => {
    const expected = Math.max(0, f.balance - hour * (f.stockout_at ? 5_000 : 300));
    return { ts: new Date(Date.parse(AS_OF) + hour * 3_600_000).toISOString(), hour, low: expected * 0.8, expected, high: expected * 1.2 };
  });
  const { balance, stockout_at, hours_to_stockout, confidence, level, horizons } = f;
  return { balance, stockout_at, hours_to_stockout, confidence, level, horizons, series };
}

export function whatIf(floatType: FloatType): WhatIfOut {
  const f = floatType === "cash" ? CASH : EMONEY;
  const s = scenario(f);
  return {
    agent_id: 1,
    float_type: floatType,
    delta_amount: 0,
    capacity: f.capacity,
    as_of: AS_OF,
    unit: "BDT",
    before: s,
    after: s,
    model_version: MODEL,
    generated_at: GENERATED,
    advisory: true,
  };
}

export const EVENTS: EventPage = {
  items: [
    {
      id: 1,
      type: "salary",
      name_en: "Garment salary week",
      name_bn: "গার্মেন্টস বেতন সপ্তাহ",
      starts_at: "2026-03-10T12:00:00Z",
      ends_at: "2026-03-11T12:00:00Z",
      district: "Dhaka",
      intensity: 2,
    },
  ],
  total: 1,
  page: 1,
  page_size: 50,
};

export const TEMPLATE_SENTENCE = "Salary week pushes cash-out up by ৳12,000.";
export const AI_SENTENCE = "Salary week is here, so more people will withdraw cash this afternoon.";

export const EXPLANATION: AgentExplanation = {
  agent_id: 1,
  target: "cash",
  demand_type: "cash_out",
  lang: "en",
  as_of: AS_OF,
  window_hours: 24,
  unit: "BDT",
  usual_bdt: 60_000,
  model_version: MODEL,
  generated_at: GENERATED,
  generated_by: "template",
  reasons: [{ factor: "salary", impact: 12_000, direction: "up", share: 0.7, sentence: TEMPLATE_SENTENCE }],
  evidence: {},
};

export const NARRATION: LlmText = {
  intent: "narrate",
  text: AI_SENTENCE,
  lang: "en",
  cited_factors: ["salary"],
  generated_by: "llm",
  provider: "anthropic",
  model: "claude-haiku-4-5-20251001",
  guard_result: "pass",
  fallback_reason: null,
  template_text: TEMPLATE_SENTENCE,
  cached: false,
  no_api_key: false,
  evidence_hash: "abc123",
  model_version: MODEL,
  generated_at: GENERATED,
  advisory: true,
};

export const NO_RECOMMENDATION: AgentRecommendation = {
  agent_id: 1,
  as_of: AS_OF,
  model_version: MODEL,
  generated_at: GENERATED,
  unit: "BDT",
  advisory: true,
  items: [],
};
