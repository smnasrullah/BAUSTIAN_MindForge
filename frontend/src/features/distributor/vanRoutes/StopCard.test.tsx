import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { StopCard } from "./StopCard";
import { vanPlan } from "./testFixtures";

describe("StopCard", () => {
  it("shows nothing when no stop is chosen or the stop is not in the plan", () => {
    const { rerender } = render(<StopCard plan={vanPlan()} stopId={null} onClose={() => undefined} />);
    expect(screen.queryByTestId("stop-card")).not.toBeInTheDocument();
    rerender(<StopCard plan={vanPlan()} stopId={99} onClose={() => undefined} />);
    expect(screen.queryByTestId("stop-card")).not.toBeInTheDocument();
  });

  it("gives the van and sequence number, the ETA, the cash to bring and the cash status", () => {
    render(<StopCard plan={vanPlan()} stopId={2} onClose={() => undefined} />);
    const card = screen.getByRole("region", { name: "Stop details" });
    expect(card).toHaveAttribute("data-health", "risk");
    expect(screen.getByTestId("stop-card-seq")).toHaveTextContent("Van 1 · stop 2");
    expect(card).toHaveTextContent("Salma Store");
    expect(card).toHaveTextContent("AGT-0012");
    expect(screen.getByTestId("stop-card-eta")).not.toHaveTextContent("Not planned");
    expect(screen.getByTestId("stop-card-amount")).toHaveTextContent("1,90,000");
    expect(screen.getByTestId("stop-card-health")).toHaveTextContent("Stockout likely before the van");
  });

  it("says an on-time stop arrives in time", () => {
    render(<StopCard plan={vanPlan()} stopId={3} onClose={() => undefined} />);
    expect(screen.getByTestId("stop-card-seq")).toHaveTextContent("Van 2 · stop 1");
    expect(screen.getByTestId("stop-card-health")).toHaveTextContent("Van arrives in time");
  });

  it("shows a skipped stop with its reason and no ETA", () => {
    render(<StopCard plan={vanPlan()} stopId={4} onClose={() => undefined} />);
    expect(screen.getByTestId("stop-card")).toHaveAttribute("data-health", "none");
    expect(screen.getByTestId("stop-card-seq")).toHaveTextContent("Not served by van");
    expect(screen.getByTestId("stop-card-eta")).toHaveTextContent("Not planned");
    expect(screen.getByText("A swap with a nearby agent covers this one.")).toBeInTheDocument();
  });

  it("closes from its labelled close button", () => {
    const onClose = vi.fn();
    render(<StopCard plan={vanPlan()} stopId={1} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Close stop details" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("gives the delivery instruction, the drive in and where the van goes next", () => {
    const { rerender } = render(<StopCard plan={vanPlan()} stopId={1} onClose={() => undefined} />);
    expect(screen.getByTestId("stop-card-instruction")).toHaveTextContent("Hand ৳1,20,000 in cash to Rahim Telecom.");
    expect(screen.getByTestId("stop-card-leg")).toHaveTextContent("From the depot");
    expect(screen.getByTestId("stop-card-leg")).toHaveTextContent("4.2 km · 14m");
    expect(screen.getByTestId("stop-card-next")).toHaveTextContent("Stop 2: Salma Store");
    rerender(<StopCard plan={vanPlan()} stopId={2} onClose={() => undefined} />);
    expect(screen.getByTestId("stop-card-leg")).toHaveTextContent("From the last stop");
    expect(screen.getByTestId("stop-card-next")).toHaveTextContent("Back to Dhaka depot");
  });

  it("has no instruction or drive for a skipped stop", () => {
    render(<StopCard plan={vanPlan()} stopId={4} onClose={() => undefined} />);
    expect(screen.queryByTestId("stop-card-instruction")).not.toBeInTheDocument();
    expect(screen.queryByTestId("stop-card-leg")).not.toBeInTheDocument();
  });
});
