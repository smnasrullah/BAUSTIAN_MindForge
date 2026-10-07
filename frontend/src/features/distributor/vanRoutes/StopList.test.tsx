import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { StopList } from "./StopList";
import { vanPlan, vanRoute, vanStop } from "./testFixtures";

describe("StopList", () => {
  it("lists each van with its stops in route order, then the skipped agents", () => {
    render(<StopList plan={vanPlan()} selectedStopId={null} onSelect={() => undefined} />);
    const routes = screen.getAllByTestId("van-route");
    expect(routes).toHaveLength(2);
    expect(within(routes[0] as HTMLElement).getAllByTestId("van-stop").map((r) => r.getAttribute("data-stop-id"))).toEqual(["1", "2"]);
    expect(within(routes[0] as HTMLElement).getByRole("heading", { level: 3 })).toHaveTextContent("Van 1");
    expect(within(screen.getByTestId("van-skipped")).getAllByTestId("van-stop")).toHaveLength(2);
  });

  it("gives every skipped agent its reason", () => {
    render(<StopList plan={vanPlan()} selectedStopId={null} onSelect={() => undefined} />);
    const reasons = screen.getAllByTestId("drop-reason");
    expect(reasons.map((r) => r.getAttribute("data-reason"))).toEqual(["swap_suggested", "cost_gt_value"]);
    expect(reasons[0]).toHaveTextContent("A swap with a nearby agent covers this one.");
    expect(reasons[1]).toHaveTextContent("The trip would cost more than the cash is worth.");
  });

  it("shows the ETA as a range when it is one, and the lateness of a late stop", () => {
    render(<StopList plan={vanPlan()} selectedStopId={null} onSelect={() => undefined} />);
    const [first, second] = screen.getAllByTestId("van-stop");
    // 06:00Z-06:20Z is 12:00-12:20 PM in Dhaka (UTC+6).
    expect(first).toHaveTextContent("12:00 PM");
    expect(first).toHaveTextContent("12:20 PM");
    expect(first).toHaveTextContent("On time");
    expect(second).toHaveTextContent("30m late");
    expect(second).toHaveTextContent("Lateness cost ৳450");
  });

  it("shows one time when the range is a single point, and the stockout chance when known", () => {
    const stop = vanStop({ eta_hi: "2026-03-10T06:00:00Z", stockout_before_arrival_p: 0.25 });
    render(<StopList plan={vanPlan({ routes: [vanRoute({ stops: [stop] })], unrouted: [] })} selectedStopId={null} onSelect={() => undefined} />);
    expect(screen.getByTestId("van-stop")).not.toHaveTextContent("–");
    expect(screen.getByTestId("van-stop")).toHaveTextContent("25% chance of running out first");
  });

  it("selects a stop on click and marks the selected one", () => {
    const onSelect = vi.fn();
    const { rerender } = render(<StopList plan={vanPlan()} selectedStopId={null} onSelect={onSelect} />);
    fireEvent.click(screen.getAllByTestId("van-stop")[1] as HTMLElement);
    expect(onSelect).toHaveBeenCalledWith(2);
    rerender(<StopList plan={vanPlan()} selectedStopId={2} onSelect={onSelect} />);
    expect(screen.getAllByTestId("van-stop")[1]).toHaveAttribute("aria-pressed", "true");
    expect(screen.getAllByTestId("van-stop")[0]).toHaveAttribute("aria-pressed", "false");
  });

  it("flags a stop that may run out before the van, and shows pins and fairness", () => {
    const risky = vanStop({ stockout_before_arrival_p: 0.6, stockout_risk_flag: true, pin: "frozen", fairness_forced: true });
    const calm = vanStop({ id: 2, stockout_before_arrival_p: 0.1, stockout_risk_flag: false });
    const excluded = vanStop({ id: 3, seq: null, eta_lo: null, eta_hi: null, status: "dropped", reason: "excluded", pin: "exclude" });
    render(<StopList plan={vanPlan({ routes: [vanRoute({ stops: [risky, calm] })], unrouted: [excluded] })} selectedStopId={null} onSelect={() => undefined} />);
    const [first, second, third] = screen.getAllByTestId("van-stop");
    expect(within(first as HTMLElement).getByTestId("stop-at-risk")).toHaveTextContent("May run out before the van");
    expect(first).toHaveTextContent("Frozen: van on its way");
    expect(first).toHaveTextContent("Added for fair service");
    expect(within(second as HTMLElement).queryByTestId("stop-at-risk")).not.toBeInTheDocument();
    expect(third).toHaveTextContent("You took this agent off the plan.");
    expect(within(third as HTMLElement).queryByTestId("stop-pin")).not.toBeInTheDocument();
  });

  it("labels a delivered stop", () => {
    const stop = vanStop({ status: "delivered", delivered_at: "2026-03-10T07:00:00Z", delivered_amount_bdt: 120_000 });
    render(<StopList plan={vanPlan({ routes: [vanRoute({ stops: [stop] })], unrouted: [] })} selectedStopId={null} onSelect={() => undefined} />);
    expect(screen.getByTestId("van-stop")).toHaveTextContent("Delivered");
    expect(screen.queryByTestId("van-skipped")).not.toBeInTheDocument();
  });

  it("reads turn by turn: depot, the drive into each stop, then the drive back", () => {
    render(<StopList plan={vanPlan()} selectedStopId={null} onSelect={() => undefined} />);
    const van1 = screen.getAllByTestId("van-route")[0] as HTMLElement;
    expect(within(van1).getByRole("list", { name: "Van 1 itinerary" })).toBeInTheDocument();
    expect(within(van1).getByTestId("van-start")).toHaveTextContent("Start at Dhaka depot");
    const legs = within(van1).getAllByTestId("van-leg");
    expect(legs.map((l) => l.getAttribute("data-km"))).toEqual(["4.2", "3.1", "4.2"]);
    expect(legs[0]).toHaveTextContent("4.2 km · 14m");
    expect(within(van1).getByTestId("van-return")).toHaveTextContent("Back to Dhaka depot");
    expect(within(van1).getByTestId("van-return")).toHaveTextContent("11.5 km in all");
    expect(within(van1).getByTestId("van-route-cost")).toHaveTextContent("Van cost ৳3,400");
  });

  it("marks an estimated drive and never invents a missing one", () => {
    const route = vanRoute({ legs: [{ from_key: "depot:DST-DHK", to_key: "agent:AGT-0011", km: 5, minutes: 20, source: "estimate", polyline: null }] });
    render(<StopList plan={vanPlan({ routes: [route], unrouted: [] })} selectedStopId={null} onSelect={() => undefined} />);
    const legs = screen.getAllByTestId("van-leg");
    expect(legs[0]).toHaveTextContent("(estimated)");
    expect(legs[1]).toHaveTextContent("Drive not stored");
  });

  it("states the saving against separate trips above the routes", () => {
    render(<StopList plan={vanPlan()} selectedStopId={null} onSelect={() => undefined} />);
    const strip = screen.getByTestId("itinerary-savings");
    expect(strip).toHaveAttribute("data-better", "true");
    expect(strip).toHaveTextContent("km less");
    expect(strip).toHaveTextContent("less than separate trips.");
  });
});
