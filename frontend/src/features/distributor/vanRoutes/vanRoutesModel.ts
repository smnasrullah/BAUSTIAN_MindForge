// Pure shaping for the van routes page (no maplibre or React import, so it is testable in jsdom).
import type { Feature, FeatureCollection, LineString } from "geojson";

import type { VanPlan, VanStop } from "../../../api/vanPlans";
import { routeColor } from "./routePalette";

export type MapView = "optimised" | "separate";
export type LngLat = [number, number];

/** Google/OSRM encoded polyline (precision 5) to [lng, lat] pairs. */
export function decodePolyline(encoded: string): LngLat[] {
  const out: LngLat[] = [];
  let index = 0;
  let lat = 0;
  let lng = 0;
  const next = (): number => {
    let result = 0;
    let shift = 0;
    let byte: number;
    do {
      byte = encoded.charCodeAt(index++) - 63;
      result |= (byte & 0x1f) << shift;
      shift += 5;
    } while (byte >= 0x20 && index < encoded.length);
    return result & 1 ? ~(result >> 1) : result >> 1;
  };
  while (index < encoded.length) {
    lat += next();
    lng += next();
    out.push([lng / 1e5, lat / 1e5]);
  }
  return out;
}

export function allStops(plan: VanPlan): VanStop[] {
  return [...plan.routes.flatMap((r) => r.stops), ...plan.unrouted];
}

export function isServed(stop: VanStop): boolean {
  return stop.status === "planned" || stop.status === "delivered";
}

export interface RouteLineProps {
  vehicle: number;
  color: string;
  /** True for a straight-line fallback: the leg has no road polyline, so it is only an approximation. */
  approx: boolean;
}

/** Depot and agent legs share keys with the road cache: "depot:<code>" and "agent:<code>". */
function pointLookup(plan: VanPlan): Map<string, LngLat> {
  const points = new Map<string, LngLat>([[`depot:${plan.depot.code}`, [plan.depot.lng, plan.depot.lat]]]);
  for (const s of allStops(plan)) points.set(`agent:${s.agent_code}`, [s.lng, s.lat]);
  return points;
}

/** One line per leg: the road polyline when the cache has one, else a straight segment. */
export function routeLines(plan: VanPlan, palette: readonly string[]): FeatureCollection<LineString, RouteLineProps> {
  const points = pointLookup(plan);
  const features: Feature<LineString, RouteLineProps>[] = [];
  for (const route of plan.routes) {
    const base = { vehicle: route.vehicle_no, color: routeColor(palette, route.vehicle_no) };
    for (const leg of route.legs) {
      const decoded = leg.polyline ? decodePolyline(leg.polyline) : [];
      const from = points.get(leg.from_key);
      const to = points.get(leg.to_key);
      const road = decoded.length >= 2;
      const coordinates = road ? decoded : from && to ? [from, to] : [];
      if (coordinates.length >= 2) {
        features.push({ type: "Feature", properties: { ...base, approx: !road }, geometry: { type: "LineString", coordinates } });
      }
    }
  }
  return { type: "FeatureCollection", features };
}

/** True when some leg of the optimised view is drawn as a straight-line fallback (no road polyline). */
export function hasApproxLegs(plan: VanPlan): boolean {
  return routeLines(plan, []).features.some((f) => f.properties.approx);
}

/** The "before" picture: every served agent gets its own out-and-back trip from the depot. */
export function spokeLines(plan: VanPlan): FeatureCollection<LineString, Record<string, never>> {
  const depot: LngLat = [plan.depot.lng, plan.depot.lat];
  const features = plan.routes
    .flatMap((r) => r.stops)
    .filter(isServed)
    .map((s): Feature<LineString, Record<string, never>> => ({
      type: "Feature",
      properties: {},
      geometry: { type: "LineString", coordinates: [depot, [s.lng, s.lat]] },
    }));
  return { type: "FeatureCollection", features };
}

/**
 * Cash status of a served stop: "risk" when the backend flags a stockout before the van arrives or the
 * van is late for the deadline, else "ok" (the van arrives in time). Skipped stops have none.
 */
export type StopHealth = "risk" | "ok";

export function stopHealth(stop: VanStop): StopHealth | null {
  if (stop.status === "dropped") return null;
  return stop.stockout_risk_flag === true || (stop.late_h ?? 0) > 0 ? "risk" : "ok";
}

export interface StopMarker {
  id: number;
  agentName: string;
  agentCode: string;
  vehicle: number | null;
  seq: number | null;
  lat: number;
  lng: number;
  dropped: boolean;
  health: StopHealth | null;
}

export function stopMarkers(plan: VanPlan): StopMarker[] {
  const placed = plan.routes.flatMap((r) => r.stops.map((s) => toMarker(s, r.vehicle_no)));
  return [...placed, ...plan.unrouted.map((s) => toMarker(s, null))];
}

function toMarker(s: VanStop, vehicle: number | null): StopMarker {
  return {
    id: s.id,
    agentName: s.agent_name,
    agentCode: s.agent_code,
    vehicle,
    seq: s.seq,
    lat: s.lat,
    lng: s.lng,
    dropped: s.status === "dropped",
    health: stopHealth(s),
  };
}

/** A stop and the van that serves it (null when the plan skips it). */
export function findStop(plan: VanPlan, id: number | null): { stop: VanStop; vehicle: number | null } | null {
  if (id === null) return null;
  for (const r of plan.routes) {
    const stop = r.stops.find((s) => s.id === id);
    if (stop) return { stop, vehicle: r.vehicle_no };
  }
  const skipped = plan.unrouted.find((s) => s.id === id);
  return skipped ? { stop: skipped, vehicle: null } : null;
}

/** South-west and north-east corners around the depot and every stop; null when there is nothing to frame. */
export function planBounds(plan: VanPlan): [LngLat, LngLat] | null {
  const pts: LngLat[] = [[plan.depot.lng, plan.depot.lat], ...allStops(plan).map((s): LngLat => [s.lng, s.lat])];
  if (pts.length === 0) return null;
  const lngs = pts.map((p) => p[0]);
  const lats = pts.map((p) => p[1]);
  return [
    [Math.min(...lngs), Math.min(...lats)],
    [Math.max(...lngs), Math.max(...lats)],
  ];
}

export type SavingsKey = "km" | "trips" | "vanBdt" | "lostBdt" | "totalBdt";

export interface SavingsRow {
  key: SavingsKey;
  unit: "km" | "count" | "bdt";
  /** Separate trips (policy A) on the same inputs. */
  before: number;
  /** This plan. */
  after: number;
  /** after - before: negative is cheaper or shorter. */
  delta: number;
}

const row = (key: SavingsKey, unit: SavingsRow["unit"], before: number, after: number): SavingsRow => ({
  key,
  unit,
  before,
  after,
  delta: after - before,
});

/** Lost value (late and skipped agents) is the total minus the van cost, on both sides. */
export function savingsRows(plan: VanPlan): SavingsRow[] {
  const base = plan.separate_trips;
  const o = plan.objective;
  return [
    row("km", "km", base.km, plan.km),
    row("trips", "count", base.trips, plan.trips),
    row("vanBdt", "bdt", base.van_bdt, o.van_bdt),
    row("lostBdt", "bdt", base.total_bdt - base.van_bdt, o.total_bdt - o.van_bdt),
    row("totalBdt", "bdt", base.total_bdt, o.total_bdt),
  ];
}

export interface SavingsHeadline {
  /** Separate-trip km minus plan km: negative means the plan drives further. */
  kmSaved: number;
  /** kmSaved as a share of the separate-trip km (0 when that is 0). */
  kmShare: number;
  /** Separate-trip total BDT minus plan total BDT (van cost plus lost value). */
  bdtSaved: number;
  bdtShare: number;
}

const share = (saved: number, before: number): number => (before > 0 ? saved / before : 0);

/** The two headline numbers of the savings panel, from the same rows as the table. */
export function savingsHeadline(plan: VanPlan): SavingsHeadline {
  const kmSaved = plan.separate_trips.km - plan.km;
  const bdtSaved = plan.separate_trips.total_bdt - plan.objective.total_bdt;
  return {
    kmSaved,
    kmShare: share(kmSaved, plan.separate_trips.km),
    bdtSaved,
    bdtShare: share(bdtSaved, plan.separate_trips.total_bdt),
  };
}

/** Hours that planned stops arrive after their deadline, summed over the plan. */
export function lateHours(plan: VanPlan): { hours: number; stops: number } {
  const late = plan.routes.flatMap((r) => r.stops).filter((s) => (s.late_h ?? 0) > 0);
  return { hours: late.reduce((sum, s) => sum + (s.late_h ?? 0), 0), stops: late.length };
}

export interface GroupRow {
  group: string;
  total: number;
  van: number;
  swap: number;
  notServed: number;
  /** (van + swap) / total, 0..1. */
  covered: number;
  maxLateH: number;
}

/** Service by agent group (area and tier): who the plan reaches, by van or by a suggested swap, and who it leaves. */
export function groupRows(plan: VanPlan): GroupRow[] {
  const rows = new Map<string, GroupRow>();
  for (const s of allStops(plan)) {
    const g = rows.get(s.group) ?? { group: s.group, total: 0, van: 0, swap: 0, notServed: 0, covered: 0, maxLateH: 0 };
    g.total += 1;
    if (isServed(s)) g.van += 1;
    else if (s.reason === "swap_suggested") g.swap += 1;
    else g.notServed += 1;
    g.maxLateH = Math.max(g.maxLateH, s.late_h ?? 0);
    rows.set(s.group, g);
  }
  return [...rows.values()]
    .map((g) => ({ ...g, covered: g.total ? (g.van + g.swap) / g.total : 0 }))
    .sort((a, b) => a.group.localeCompare(b.group));
}

/** "urban/tier2" -> { area: "urban", tier: 2 }; anything else keeps its raw text. */
export function parseGroup(group: string): { area: "urban" | "rural"; tier: number } | null {
  const hit = /^(urban|rural)\/tier(\d+)$/.exec(group);
  if (!hit) return null;
  return { area: hit[1] === "rural" ? "rural" : "urban", tier: Number(hit[2]) };
}

export interface Controls {
  vehicles: number;
  capacityBdt: number;
  cashCapBdt: number;
}

export const CONTROL_LIMITS = {
  vehicles: { min: 1, max: 10 },
  amount: { min: 100_000, max: 3_000_000, step: 100_000 },
} as const;

function num(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

/** The controls as the plan was solved (params.config), so the sliders start where the plan is. */
export function controlsOf(plan: VanPlan): Controls {
  const cfg = plan.params["config"];
  const c: Record<string, unknown> = typeof cfg === "object" && cfg !== null ? (cfg as Record<string, unknown>) : {};
  return {
    vehicles: Math.round(num(c["vehicles"], plan.routes.length || 2)),
    capacityBdt: num(c["capacity_bdt"], 1_500_000),
    cashCapBdt: num(c["cash_cap_bdt"], 1_500_000),
  };
}

export function sameControls(a: Controls, b: Controls): boolean {
  return a.vehicles === b.vehicles && a.capacityBdt === b.capacityBdt && a.cashCapBdt === b.cashCapBdt;
}

/** A van carries the smaller of its capacity and the safety cash cap. */
export function loadLimit(c: Controls): number {
  return Math.min(c.capacityBdt, c.cashCapBdt);
}
