import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PlanControls } from "./PlanControls";
import type { Controls } from "./vanRoutesModel";

const VALUE: Controls = { vehicles: 2, capacityBdt: 1_500_000, cashCapBdt: 1_500_000 };

describe("PlanControls", () => {
  it("shows the vans, the two amounts and the load limit", () => {
    render(<PlanControls value={{ ...VALUE, capacityBdt: 900_000 }} onChange={() => undefined} busy={false} />);
    expect(screen.getByTestId("vans-count")).toHaveTextContent("2");
    expect(screen.getByLabelText("Van capacity")).toHaveValue("900000");
    expect(screen.getByLabelText("Cash cap per van")).toHaveValue("1500000");
    // A van carries the smaller of capacity and cash cap.
    expect(screen.getByTestId("load-limit")).toHaveTextContent("Each van carries at most ৳9 lakh.");
  });

  it("changes the number of vans one step at a time", () => {
    const onChange = vi.fn();
    render(<PlanControls value={VALUE} onChange={onChange} busy={false} />);
    fireEvent.click(screen.getByRole("button", { name: "One van more" }));
    expect(onChange).toHaveBeenLastCalledWith({ ...VALUE, vehicles: 3 });
    fireEvent.click(screen.getByRole("button", { name: "One van fewer" }));
    expect(onChange).toHaveBeenLastCalledWith({ ...VALUE, vehicles: 1 });
  });

  it("stops at one and ten vans", () => {
    const { rerender } = render(<PlanControls value={{ ...VALUE, vehicles: 1 }} onChange={() => undefined} busy={false} />);
    expect(screen.getByTestId("vans-dec")).toBeDisabled();
    rerender(<PlanControls value={{ ...VALUE, vehicles: 10 }} onChange={() => undefined} busy={false} />);
    expect(screen.getByTestId("vans-inc")).toBeDisabled();
  });

  it("reports capacity and cash cap changes from the sliders", () => {
    const onChange = vi.fn();
    render(<PlanControls value={VALUE} onChange={onChange} busy={false} />);
    fireEvent.change(screen.getByTestId("capacity-range"), { target: { value: "900000" } });
    expect(onChange).toHaveBeenLastCalledWith({ ...VALUE, capacityBdt: 900_000 });
    fireEvent.change(screen.getByTestId("cash-cap-range"), { target: { value: "600000" } });
    expect(onChange).toHaveBeenLastCalledWith({ ...VALUE, cashCapBdt: 600_000 });
  });

  it("says it is solving again while busy, and stays editable", () => {
    render(<PlanControls value={VALUE} onChange={() => undefined} busy />);
    expect(screen.getByTestId("controls-status")).toHaveTextContent("Re-solving");
    expect(screen.getByTestId("plan-controls")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByTestId("vans-inc")).toBeEnabled();
  });
});
