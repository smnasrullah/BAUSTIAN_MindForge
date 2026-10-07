import { describe, expect, it } from "vitest";

import { itinerary, stopTrip } from "./itinerary";
import { vanPlan, vanRoute } from "./testFixtures";

describe("itinerary", () => {
  it("runs depot, each stop with the leg that reaches it, then the drive back", () => {
    const steps = itinerary(vanRoute());
    expect(steps.map((s) => s.kind)).toEqual(["depot", "stop", "stop", "return"]);
    const [, first, second, back] = steps;
    expect(first?.kind === "stop" && first.stop.id).toBe(1);
    expect(first?.kind === "stop" && first.leg).toEqual({ km: 4.2, minutes: 14, source: "road_cache" });
    expect(second?.kind === "stop" && second.leg?.km).toBe(3.1);
    expect(second?.kind === "stop" && second.cumKm).toBeCloseTo(7.3);
    expect(back?.kind === "return" && back.leg?.minutes).toBe(15);
    expect(back?.kind === "return" && back.cumKm).toBeCloseTo(11.5);
  });

  it("leaves a missing leg empty instead of inventing a distance", () => {
    const steps = itinerary(vanRoute({ legs: [] }));
    expect(steps[1]?.kind === "stop" && steps[1].leg).toBeNull();
    expect(steps[3]?.kind === "return" && steps[3].leg).toBeNull();
  });
});

describe("stopTrip", () => {
  it("gives the leg in and the next stop", () => {
    const trip = stopTrip(vanPlan(), 1);
    expect(trip?.fromDepot).toBe(true);
    expect(trip?.leg?.km).toBe(4.2);
    expect(trip?.next !== "depot" && trip?.next.id).toBe(2);
  });

  it("sends the van back to the depot after the last stop", () => {
    const trip = stopTrip(vanPlan(), 2);
    expect(trip?.fromDepot).toBe(false);
    expect(trip?.leg?.km).toBe(3.1);
    expect(trip?.next).toBe("depot");
  });

  it("has nothing for a skipped or unknown stop", () => {
    expect(stopTrip(vanPlan(), 4)).toBeNull();
    expect(stopTrip(vanPlan(), 99)).toBeNull();
    expect(stopTrip(vanPlan(), null)).toBeNull();
  });
});
