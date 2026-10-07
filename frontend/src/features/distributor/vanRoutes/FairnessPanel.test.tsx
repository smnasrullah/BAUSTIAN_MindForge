import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FairnessPanel } from "./FairnessPanel";
import { vanPlan, vanRoute, vanStop } from "./testFixtures";

describe("FairnessPanel", () => {
  it("shows service by area and tier: by van, by swap, and not served", () => {
    render(<FairnessPanel plan={vanPlan()} />);
    const rows = screen.getAllByTestId("fairness-row");
    expect(rows.map((r) => r.getAttribute("data-group"))).toEqual(["rural/tier3", "urban/tier1", "urban/tier2"]);
    const rural = rows[0] as HTMLElement;
    expect(within(rural).getByRole("rowheader")).toHaveTextContent("Rural, tier 3");
    // One van stop, one covered by a swap, one dropped because it costs more than it is worth.
    expect(within(rural).getAllByRole("cell").map((c) => c.textContent)).toEqual(["1", "1", "1", "67%", "–"]);
    expect(within(rows[2] as HTMLElement).getByTestId("fairness-covered")).toHaveTextContent("100%");
  });

  it("shows the longest lateness in a group", () => {
    render(<FairnessPanel plan={vanPlan()} />);
    expect(within(screen.getAllByTestId("fairness-row")[2] as HTMLElement).getAllByRole("cell").at(-1)).toHaveTextContent("30m");
  });

  it("keeps a group name it cannot parse", () => {
    const plan = vanPlan({ routes: [vanRoute({ stops: [vanStop({ group: "hill-tracts" })] })], unrouted: [] });
    render(<FairnessPanel plan={plan} />);
    expect(screen.getByRole("rowheader")).toHaveTextContent("hill-tracts");
  });

  it("says so when there are no stops to compare", () => {
    render(<FairnessPanel plan={vanPlan({ routes: [], unrouted: [] })} />);
    expect(screen.getByText("There are no stops to compare yet.")).toBeInTheDocument();
    expect(screen.queryByTestId("fairness-row")).not.toBeInTheDocument();
  });
});
