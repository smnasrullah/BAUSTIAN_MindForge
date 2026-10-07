// Turn-by-turn view of one van route: depot, each stop with the leg that reaches it, and the drive back.
// Pure (no React or maplibre), so it is testable in jsdom. Every number is a backend leg value.
import type { VanLeg, VanPlan, VanRoute, VanStop } from "../../../api/vanPlans";

export interface ItineraryLeg {
  km: number;
  minutes: number;
  source: VanLeg["source"];
}

export type ItineraryStep =
  | { kind: "depot" }
  | { kind: "stop"; stop: VanStop; leg: ItineraryLeg | null; cumKm: number }
  | { kind: "return"; leg: ItineraryLeg | null; cumKm: number };

const toLeg = (l: VanLeg): ItineraryLeg => ({ km: l.km, minutes: l.minutes, source: l.source });

/** Depot, stops in visiting order, return. A missing leg stays null: no distance is made up. */
export function itinerary(route: VanRoute): ItineraryStep[] {
  const into = new Map(route.legs.map((l) => [l.to_key, l]));
  const back = route.legs.find((l) => l.to_key.startsWith("depot:"));
  const steps: ItineraryStep[] = [{ kind: "depot" }];
  let cumKm = 0;
  for (const stop of route.stops) {
    const leg = into.get(`agent:${stop.agent_code}`);
    cumKm += leg?.km ?? 0;
    steps.push({ kind: "stop", stop, leg: leg ? toLeg(leg) : null, cumKm });
  }
  cumKm += back?.km ?? 0;
  steps.push({ kind: "return", leg: back ? toLeg(back) : null, cumKm });
  return steps;
}

export interface StopTrip {
  /** The leg that reaches this stop (from the depot or the previous stop). */
  leg: ItineraryLeg | null;
  /** True when the van comes straight from the depot. */
  fromDepot: boolean;
  /** The next stop, or "depot" when the van drives back after this one. */
  next: VanStop | "depot";
}

/** Where the van comes from and goes next around one served stop; null for a skipped stop. */
export function stopTrip(plan: VanPlan, stopId: number | null): StopTrip | null {
  if (stopId === null) return null;
  for (const route of plan.routes) {
    const steps = itinerary(route);
    const at = steps.findIndex((s) => s.kind === "stop" && s.stop.id === stopId);
    if (at < 0) continue;
    const here = steps[at];
    const after = steps[at + 1];
    if (here?.kind !== "stop") return null;
    return { leg: here.leg, fromDepot: at === 1, next: after?.kind === "stop" ? after.stop : "depot" };
  }
  return null;
}
