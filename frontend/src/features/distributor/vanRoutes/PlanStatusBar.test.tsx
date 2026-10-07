import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PlanStatusBar } from "./PlanStatusBar";
import { vanPlan } from "./testFixtures";

describe("PlanStatusBar", () => {
  it("shows a pending plan with its distance source, solver and advisory notice", () => {
    render(<PlanStatusBar plan={vanPlan()} />);
    const bar = screen.getByTestId("plan-status-bar");
    expect(bar).toHaveAttribute("data-status", "pending");
    expect(screen.getByTestId("plan-status")).toHaveTextContent("Waiting for your decision");
    expect(screen.getByTestId("plan-distance-source")).toHaveTextContent("Road distances from the cache");
    expect(bar).toHaveTextContent("Solver ortools");
    expect(bar).toHaveTextContent("Solved in 480 ms");
    expect(bar).toHaveTextContent("forecast-v3");
    expect(bar).toHaveTextContent("Advisory only. You decide; no money moves from this page.");
    expect(screen.queryByTestId("plan-decision")).not.toBeInTheDocument();
  });

  it("labels estimated distances so nobody reads them as road data", () => {
    render(<PlanStatusBar plan={vanPlan({ distance_source: "estimate" })} />);
    expect(screen.getByTestId("plan-distance-source")).toHaveTextContent("Estimated distances (no road data)");
    expect(screen.getByTestId("plan-status-bar")).toHaveAttribute("data-distance-source", "estimate");
  });

  it("shows who decided, when, and the note once the plan is decided", () => {
    render(<PlanStatusBar plan={vanPlan({ status: "approved", decided_at: "2026-03-10T07:30:00Z", note: "Both vans are free today" })} />);
    expect(screen.getByTestId("plan-status")).toHaveTextContent("Approved");
    expect(screen.getByTestId("plan-decision")).toHaveTextContent("Both vans are free today");
  });

  it.each([
    ["rejected", "Rejected"],
    ["superseded", "Replaced by a newer plan"],
  ] as const)("names the %s status", (status, text) => {
    render(<PlanStatusBar plan={vanPlan({ status })} />);
    expect(screen.getByTestId("plan-status")).toHaveTextContent(text);
  });
});
