import type { AdminUser, AuditItem, DataSummary, EventItem, JobOut, LlmLogItem, LlmStatus, LlmUsage } from "../../api/types";

const NOW = "2026-10-03T08:00:00Z";

export function adminUser(over: Partial<AdminUser> = {}): AdminUser {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    email: "agent.mirpur@agentpulse.demo",
    full_name: "Mirpur agent",
    role: "agent",
    agent_id: 1,
    agent_code: "AGT-0001",
    distributor_id: 1,
    distributor_code: "DST-DHK",
    is_active: true,
    is_demo: false,
    is_pending: false,
    is_rejected: false,
    last_login_at: null,
    created_at: NOW,
    ...over,
  };
}

export function eventItem(over: Partial<EventItem> = {}): EventItem {
  return {
    id: 7,
    type: "hat_bazar",
    name_en: "Dhaka weekly hat",
    name_bn: "ঢাকা সাপ্তাহিক হাট",
    starts_at: "2026-04-28T04:00:00Z",
    ends_at: "2026-04-28T12:00:00Z",
    district: "Dhaka",
    intensity: 1.4,
    ...over,
  };
}

export function auditItem(over: Partial<AuditItem> = {}): AuditItem {
  return {
    id: 3,
    created_at: NOW,
    user_email: "admin@agentpulse.demo",
    user_role: "admin",
    action: "user.create",
    entity_type: "user",
    entity_id: "11111111-1111-1111-1111-111111111111",
    note: null,
    payload: '{"after":{"role":"agent"}}',
    ...over,
  };
}

export function job(over: Partial<JobOut> = {}): JobOut {
  return {
    id: 4,
    kind: "generate_data",
    status: "running",
    progress: 55,
    step: "precompute:forecast",
    error: null,
    result: [],
    started_by_email: "admin@agentpulse.demo",
    created_at: NOW,
    updated_at: NOW,
    finished_at: null,
    ...over,
  };
}

export function dataSummary(): DataSummary {
  return {
    seed: 42,
    configured_seed: 42,
    data_version: "1.0.0",
    period: { start: "2026-01-04T18:00:00Z", end: "2026-05-04T18:00:00Z", holdout_start: "2026-04-20T18:00:00Z", sim_now: "2026-04-30T14:00:00Z" },
    counts: [
      { table: "agents", rows: 300 },
      { table: "transactions", rows: 1036800 },
    ],
    labelled_anomalous_agents: 9,
    generated_at: NOW,
  };
}

export function llmLog(over: Partial<LlmLogItem> = {}): LlmLogItem {
  return {
    id: 9,
    created_at: NOW,
    user_id: null,
    user_email: "dist.dhaka@agentpulse.demo",
    intent: "narrate",
    provider: "cache",
    model: null,
    lang: "en",
    prompt_tokens: null,
    completion_tokens: null,
    latency_ms: 2,
    generated_by: "llm",
    guard_result: "pass",
    cache_hit: true,
    error: null,
    ...over,
  };
}

export function llmUsage(): LlmUsage {
  const day = (d: string, calls: number) => ({
    day: d,
    calls,
    live_calls: 1,
    cache_hits: 1,
    replay: 0,
    template: 1,
    guard_failures: 0,
    prompt_tokens: 100,
    completion_tokens: 50,
  });
  return {
    days: [day("2026-10-02", 3), day("2026-10-03", 4)],
    calls_today: 400,
    daily_cap: 500,
    cap_used: 0.8,
    total_calls: 7,
    cache_hit_rate: 0.2857,
    avg_latency_ms: 850,
    p95_latency_ms: 1200,
    guard_failures: 0,
    generated_at: NOW,
  };
}

export function llmStatus(): LlmStatus {
  return {
    configured: "auto",
    mode: "replay",
    live: false,
    model: null,
    key_configured: false,
    replay_entries: 12,
    replay_skipped: null,
    no_api_key: true,
    calls_today: 0,
    daily_cap: 500,
    user_calls_per_min: 6,
    last_error: null,
    last_error_at: null,
    generated_at: NOW,
  };
}
