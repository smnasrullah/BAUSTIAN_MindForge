// Van route plans (F14): Zod schemas that mirror backend/app/schemas/van_plan.py, the calls, and the
// TanStack Query hooks. Responses are parsed, so a contract drift shows as an error state, not as NaN.
// Imported from "zod/v3", not "zod": that build is a separate module graph, so it stays in this lazy
// page chunk. Sharing the v4 chunk with the login form pushed the /login first load over its 250 KB
// budget (docs/DECISIONS.md V15).
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod/v3";

import { api } from "../lib/api";
import type { Lang } from "./types";

export const distanceSourceSchema = z.enum(["road_cache", "estimate"]);
export const planStatusSchema = z.enum(["pending", "approved", "rejected", "superseded"]);
export const stopStatusSchema = z.enum(["planned", "dropped", "delivered"]);
export const dropReasonSchema = z.enum(["swap_suggested", "cost_gt_value", "capacity", "excluded"]);
export const stopPinSchema = z.enum(["lock", "include", "exclude", "frozen"]);

const timestamp = z.string();

export const vanStopSchema = z.object({
  id: z.number(),
  seq: z.number().nullable(),
  agent_id: z.number(),
  agent_code: z.string(),
  agent_name: z.string(),
  lat: z.number(),
  lng: z.number(),
  group: z.string(),
  amount_bdt: z.number(),
  source_quantile: z.string(),
  eta_lo: timestamp.nullable(),
  eta_hi: timestamp.nullable(),
  deadline: timestamp.nullable(),
  late_h: z.number().nullable(),
  penalty_bdt: z.number(),
  lost_per_h_bdt: z.number(),
  stockout_before_arrival_p: z.number().nullable(),
  status: stopStatusSchema,
  reason: dropReasonSchema.nullable(),
  delivered_at: timestamp.nullable(),
  delivered_amount_bdt: z.number().nullable(),
  stockout_risk_flag: z.boolean().nullable().optional(),
  pin: stopPinSchema.nullable().optional(),
  fairness_forced: z.boolean().optional(),
});

export const vanLegSchema = z.object({
  from_key: z.string(),
  to_key: z.string(),
  km: z.number(),
  minutes: z.number(),
  source: distanceSourceSchema,
  polyline: z.string().nullable(),
});

export const vanRouteSchema = z.object({
  id: z.number(),
  vehicle_no: z.number(),
  km: z.number(),
  minutes: z.number(),
  cash_load_bdt: z.number(),
  cost_bdt: z.number(),
  legs: z.array(vanLegSchema),
  stops: z.array(vanStopSchema),
});

export const vanObjectiveSchema = z.object({
  van_fixed_bdt: z.number(),
  van_km_bdt: z.number(),
  van_time_bdt: z.number(),
  late_penalty_bdt: z.number(),
  skip_penalty_bdt: z.number(),
  van_bdt: z.number(),
  total_bdt: z.number(),
});

export const vanComparisonSchema = z.object({
  km: z.number(),
  trips: z.number(),
  van_bdt: z.number(),
  total_bdt: z.number(),
});

export const vanDepotSchema = z.object({ code: z.string(), name: z.string(), lat: z.number(), lng: z.number() });

const vanPlanSummarySchema = z.object({
  id: z.number(),
  distributor_id: z.number(),
  status: planStatusSchema,
  planned_at: timestamp,
  clock_origin: timestamp,
  horizon_h: z.number(),
  solver: z.string(),
  stopped_by: z.string(),
  solve_ms: z.number(),
  distance_source: distanceSourceSchema,
  model_version: z.string().nullable(),
  generated_at: timestamp,
  input_hash: z.string(),
  served: z.number(),
  dropped: z.number(),
  trips: z.number(),
  km: z.number(),
  total_bdt: z.number(),
  advisory: z.literal(true),
});

export const vanPlanSchema = vanPlanSummarySchema.extend({
  reused: z.boolean(),
  params: z.record(z.string(), z.unknown()),
  objective: vanObjectiveSchema,
  separate_trips: vanComparisonSchema,
  depot: vanDepotSchema,
  routes: z.array(vanRouteSchema),
  unrouted: z.array(vanStopSchema),
  decided_by: z.string().nullable(),
  decided_at: timestamp.nullable(),
  note: z.string().nullable(),
});

export const vanPlanPageSchema = z.object({
  items: z.array(vanPlanSummarySchema),
  total: z.number(),
  page: z.number(),
  page_size: z.number(),
});

export const vanNarrativeSchema = z.object({
  plan_id: z.number(),
  lang: z.enum(["bn", "en"]),
  text: z.string(),
  generated_by: z.enum(["llm", "template", "replay"]),
  model_version: z.string().nullable(),
  generated_at: timestamp,
  distance_source: distanceSourceSchema,
});

export type DistanceSource = z.infer<typeof distanceSourceSchema>;
export type PlanStatus = z.infer<typeof planStatusSchema>;
export type DropReason = z.infer<typeof dropReasonSchema>;
export type VanStop = z.infer<typeof vanStopSchema>;
export type VanLeg = z.infer<typeof vanLegSchema>;
export type VanRoute = z.infer<typeof vanRouteSchema>;
export type VanPlan = z.infer<typeof vanPlanSchema>;
export type VanPlanSummary = z.infer<typeof vanPlanSummarySchema>;
export type VanPlanPage = z.infer<typeof vanPlanPageSchema>;
export type VanNarrative = z.infer<typeof vanNarrativeSchema>;

export interface VanVehicles {
  count?: number;
  capacity_bdt?: number;
  cash_cap_bdt?: number;
}

export interface VanPlanCreate {
  horizon_h?: number;
  vehicles?: VanVehicles;
}

export interface VanDecisionIn {
  decision: "approve" | "reject";
  note: string;
}

export interface VanPlanListQuery {
  status?: PlanStatus;
  page_size?: number;
}

// Query keys live here, not in keys.ts: that file is in the first-load bundle (budget in
// docs/DECISIONS.md V15) and only this feature uses them.
export const vanKeys = {
  lists: ["van-plans", "list"] as const,
  list: (q: VanPlanListQuery = {}) => ["van-plans", "list", q] as const,
  detail: (id: number) => ["van-plans", "detail", id] as const,
  narrative: (id: number, lang: Lang) => ["van-plans", "narrative", id, lang] as const,
};

const BASE = "/distributor/van-plans";

export async function createVanPlan(body: VanPlanCreate = {}): Promise<VanPlan> {
  return vanPlanSchema.parse((await api.post<unknown>(BASE, body)).data);
}

export async function getVanPlan(id: number): Promise<VanPlan> {
  return vanPlanSchema.parse((await api.get<unknown>(`${BASE}/${id}`)).data);
}

export async function listVanPlans(q: VanPlanListQuery = {}): Promise<VanPlanPage> {
  return vanPlanPageSchema.parse((await api.get<unknown>(BASE, { params: q })).data);
}

export async function decideVanPlan(id: number, body: VanDecisionIn): Promise<VanPlan> {
  return vanPlanSchema.parse((await api.post<unknown>(`${BASE}/${id}/decision`, body)).data);
}

export async function getVanNarrative(id: number, lang: Lang): Promise<VanNarrative> {
  return vanNarrativeSchema.parse((await api.get<unknown>(`${BASE}/${id}/narrative`, { params: { lang } })).data);
}

export function useVanPlans(q: VanPlanListQuery = {}) {
  return useQuery({ queryKey: vanKeys.list(q), queryFn: () => listVanPlans(q), placeholderData: keepPreviousData });
}

export function useVanPlan(id: number | null) {
  return useQuery({
    queryKey: vanKeys.detail(id ?? 0),
    queryFn: () => getVanPlan(id ?? 0),
    enabled: id !== null,
  });
}

export function useVanNarrative(id: number | null, lang: Lang) {
  return useQuery({
    queryKey: vanKeys.narrative(id ?? 0, lang),
    queryFn: () => getVanNarrative(id ?? 0, lang),
    enabled: id !== null,
  });
}

/** Solve a plan now. The result goes straight into the detail cache, so the page shows it at once. */
export function useCreateVanPlan() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: VanPlanCreate) => createVanPlan(body),
    onSuccess: (plan) => {
      client.setQueryData(vanKeys.detail(plan.id), plan);
      void client.invalidateQueries({ queryKey: vanKeys.lists });
    },
  });
}

export function useDecideVanPlan() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: VanDecisionIn }) => decideVanPlan(id, body),
    onSuccess: (plan) => {
      client.setQueryData(vanKeys.detail(plan.id), plan);
      // Not awaited: the page pins the decided plan in the URL first, then the lists refresh.
      void client.invalidateQueries({ queryKey: vanKeys.lists });
    },
  });
}
