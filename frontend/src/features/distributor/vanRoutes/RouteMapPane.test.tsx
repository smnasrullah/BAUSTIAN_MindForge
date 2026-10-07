import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useControlRoomStore } from "../controlRoom/controlRoomStore";
import { RouteMapPane } from "./RouteMapPane";
import { vanPlan } from "./testFixtures";

// The real map needs WebGL; the pane's own job (frame, legend, states, wiring) is tested with a stand-in.
vi.mock("./RouteMap", async () => {
  const { createElement } = await import("react");
  return {
    default: (props: { view: string; selectedStopId: number | null; onlineTiles: boolean; label: string; onSelect: (id: number) => void; onFail: () => void }) =>
      createElement(
        "div",
        {
          "data-testid": "stub-map",
          "data-view": props.view,
          "data-selected": String(props.selectedStopId),
          "data-tiles": props.onlineTiles ? "online" : "offline",
          "aria-label": props.label,
        },
        createElement("button", { type: "button", onClick: () => props.onSelect(3) }, "pick"),
        createElement("button", { type: "button", onClick: props.onFail }, "break"),
      ),
  };
});

const base = { status: "ready" as const, onRetry: () => undefined, retrying: false, view: "optimised" as const, selectedStopId: null, onSelect: () => undefined, onClear: () => undefined, busy: false };

describe("RouteMapPane", () => {
  it("keeps the offline map by default and turns street tiles on from its toggle", async () => {
    useControlRoomStore.getState().setOnlineTiles(false);
    render(<RouteMapPane {...base} plan={vanPlan()} />);
    const map = await screen.findByTestId("stub-map");
    expect(map).toHaveAttribute("data-tiles", "offline");
    const toggle = screen.getByTestId("route-tiles-toggle");
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(toggle);
    expect(screen.getByTestId("stub-map")).toHaveAttribute("data-tiles", "online");
    expect(screen.getByTestId("route-tiles-toggle")).toHaveAttribute("aria-pressed", "true");
    useControlRoomStore.getState().setOnlineTiles(false);
  });

  it("renders the map with a screen-reader summary and a legend with one entry per van", async () => {
    render(<RouteMapPane {...base} plan={vanPlan()} />);
    const map = await screen.findByTestId("stub-map");
    expect(map).toHaveAttribute("aria-label", "Van routes: 2 vans, 3 stops, 2 not served by van");
    const legend = screen.getByTestId("route-legend");
    expect(legend).toHaveTextContent("Van 1");
    expect(legend).toHaveTextContent("Van 2");
    expect(legend).toHaveTextContent("Not served by van");
    // Cash status keys: stop 2 is late (red), stops 1 and 3 arrive in time (green).
    expect(screen.getByTestId("legend-risk")).toHaveTextContent("Stockout likely before the van");
    expect(screen.getByTestId("legend-ok")).toHaveTextContent("Van arrives in time");
  });

  it("opens the stop card for the chosen stop and closes it", async () => {
    const onClear = vi.fn();
    const { rerender } = render(<RouteMapPane {...base} plan={vanPlan()} onClear={onClear} />);
    await screen.findByTestId("stub-map");
    expect(screen.queryByTestId("stop-card")).not.toBeInTheDocument();
    rerender(<RouteMapPane {...base} plan={vanPlan()} selectedStopId={2} onClear={onClear} />);
    expect(screen.getByTestId("stop-card")).toHaveAttribute("data-stop-id", "2");
    fireEvent.click(screen.getByTestId("stop-card-close"));
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it("explains the dashed spokes in the separate-trips view", async () => {
    render(<RouteMapPane {...base} plan={vanPlan()} view="separate" />);
    expect(await screen.findByTestId("stub-map")).toHaveAttribute("data-view", "separate");
    expect(screen.getByTestId("route-legend")).toHaveTextContent("One trip per agent");
    expect(screen.getByTestId("route-legend")).not.toHaveTextContent("Van 1");
  });

  it("passes the selection through and reports a click on a stop", async () => {
    const onSelect = vi.fn();
    render(<RouteMapPane {...base} plan={vanPlan()} selectedStopId={2} onSelect={onSelect} />);
    expect(await screen.findByTestId("stub-map")).toHaveAttribute("data-selected", "2");
    fireEvent.click(screen.getByRole("button", { name: "pick" }));
    expect(onSelect).toHaveBeenCalledWith(3);
  });

  it("falls back to a retry panel when the map cannot start, and tries again", async () => {
    render(<RouteMapPane {...base} plan={vanPlan()} />);
    fireEvent.click(await screen.findByRole("button", { name: "break" }));
    expect(screen.getByText("The map could not start")).toBeInTheDocument();
    expect(screen.queryByTestId("stub-map")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByTestId("stub-map")).toBeInTheDocument();
  });

  it("shows a skeleton while the plan loads", () => {
    render(<RouteMapPane {...base} plan={undefined} status="pending" />);
    expect(screen.queryByTestId("route-legend")).not.toBeInTheDocument();
    expect(screen.getByTestId("route-map-pane")).toBeInTheDocument();
  });

  it("shows an error with a retry when the plan fails to load", () => {
    const onRetry = vi.fn();
    render(<RouteMapPane {...base} plan={undefined} status="error" onRetry={onRetry} />);
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("dims the old plan while a new one is being solved", () => {
    render(<RouteMapPane {...base} plan={vanPlan()} busy />);
    expect(screen.getByTestId("route-map-busy")).toBeInTheDocument();
    expect(screen.getByTestId("route-map-pane")).toHaveAttribute("aria-busy", "true");
  });
});
