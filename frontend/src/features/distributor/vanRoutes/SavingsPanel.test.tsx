import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SavingsPanel } from "./SavingsPanel";
import { vanPlan } from "./testFixtures";

describe("SavingsPanel", () => {
  it("compares km, trips and cost with separate trips", () => {
    render(<SavingsPanel plan={vanPlan()} />);
    const km = screen.getByTestId("savings-km");
    expect(km).toHaveTextContent("58.0");
    expect(km).toHaveTextContent("31.5");
    expect(km).toHaveTextContent("26.5 less");
    expect(screen.getByTestId("savings-trips")).toHaveTextContent("1 less");
    const total = screen.getByTestId("savings-totalBdt");
    expect(within(total).getByText("৳12.3k")).toBeInTheDocument();
    expect(within(total).getByText("৳9.8k")).toBeInTheDocument();
    expect(total).toHaveTextContent("৳2.5k less");
  });

  it("shows a worse row as worse, not as a saving", () => {
    render(<SavingsPanel plan={vanPlan()} />);
    // Lost value goes up (late and skipped agents) even though the vans cost less.
    const lost = screen.getByTestId("savings-lostBdt");
    expect(lost).toHaveTextContent("৳900 more");
    expect(within(lost).getByText("৳900 more").closest("span")).toHaveAttribute("data-better", "false");
    expect(screen.queryByTestId("savings-worse")).not.toBeInTheDocument();
  });

  it("warns when the plan costs more in total than separate trips", () => {
    const plan = vanPlan();
    render(<SavingsPanel plan={vanPlan({ objective: { ...plan.objective, total_bdt: 15_000 } })} />);
    expect(screen.getByTestId("savings-worse")).toHaveTextContent("costs more than separate trips");
    expect(screen.getByTestId("savings-totalBdt")).toHaveTextContent("more");
  });

  it("reports an unchanged figure as no change", () => {
    const plan = vanPlan();
    render(<SavingsPanel plan={vanPlan({ trips: 3, separate_trips: { ...plan.separate_trips, trips: 3 } })} />);
    expect(screen.getByTestId("savings-trips")).toHaveTextContent("No change");
  });

  it("states the late hours of the plan, or that every stop is on time", () => {
    const { unmount } = render(<SavingsPanel plan={vanPlan()} />);
    expect(screen.getByTestId("savings-late")).toHaveTextContent("Late arrivals: 30m across 1 stops.");
    unmount();
    const plan = vanPlan();
    render(<SavingsPanel plan={vanPlan({ routes: plan.routes.map((r) => ({ ...r, stops: r.stops.map((s) => ({ ...s, late_h: null })) })) })} />);
    expect(screen.getByTestId("savings-late")).toHaveTextContent("Every served stop arrives before its deadline.");
  });

  it("labels its numbers as rule-based and synthetic", () => {
    render(<SavingsPanel plan={vanPlan()} />);
    expect(screen.getByTestId("source-chip")).toHaveAttribute("data-source", "rule");
    expect(screen.getByText(/Synthetic data/)).toBeInTheDocument();
  });

  it("leads with the distance and the total cost saved, and the approval status", () => {
    render(<SavingsPanel plan={vanPlan()} />);
    const km = screen.getByTestId("savings-head-km");
    expect(km).toHaveTextContent("Distance saved");
    expect(km).toHaveTextContent("26.5 km");
    expect(km).toHaveTextContent("46% less than separate trips");
    const bdt = screen.getByTestId("savings-head-bdt");
    expect(bdt).toHaveTextContent("Cost saved");
    expect(bdt).toHaveTextContent("৳2.5k");
    expect(bdt).toHaveTextContent("20% less than separate trips");
    expect(screen.getByTestId("savings-status")).toHaveTextContent("Waiting for your decision");
  });

  it("names extra cost as extra, never as a saving, and follows the decision", () => {
    const plan = vanPlan();
    render(<SavingsPanel plan={vanPlan({ status: "approved", objective: { ...plan.objective, total_bdt: 15_000 } })} />);
    const bdt = screen.getByTestId("savings-head-bdt");
    expect(bdt).toHaveAttribute("data-better", "false");
    expect(bdt).toHaveTextContent("Extra cost");
    expect(bdt).toHaveTextContent("22% more than separate trips");
    expect(screen.getByTestId("savings-status")).toHaveAttribute("data-status", "approved");
    expect(screen.getByTestId("savings-status")).toHaveTextContent("Approved");
  });
});
