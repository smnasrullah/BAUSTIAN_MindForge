import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { VanPlan } from "../../../api/vanPlans";
import { useToastStore } from "../../../components/ui/toastStore";
import { api as realApi } from "../../../lib/api";
import type { FakeApi } from "../../../test/fakeApi";
import { signIn } from "../../auth/testUtils";
import { renderAt } from "../testRender";
import { vanNarrative, vanPage, vanPlan } from "./testFixtures";
import { VanRoutesPage } from "./VanRoutesPage";

vi.mock("../../../lib/api", async () => {
  const { createFakeApi } = await import("../../../test/fakeApi");
  return { api: createFakeApi(), authClient: { post: vi.fn() }, refreshAccessToken: vi.fn() };
});

// The real map needs WebGL; it has its own test. This stand-in shows which view and selection it got.
vi.mock("./RouteMap", async () => {
  const { createElement } = await import("react");
  return {
    default: (props: { view: string; selectedStopId: number | null; onSelect: (id: number) => void }) =>
      createElement(
        "button",
        { type: "button", "data-testid": "stub-map", "data-view": props.view, "data-selected": String(props.selectedStopId), onClick: () => props.onSelect(2) },
        "map",
      ),
  };
});

const api = realApi as unknown as FakeApi;
const BASE = "/distributor/van-plans";

function open(url = "/distributor/van-routes") {
  return renderAt(url, "/distributor/van-routes", <VanRoutesPage />);
}

function serve(plan: VanPlan | null) {
  api.on("get", BASE, () => vanPage(plan ? [plan] : []));
  if (plan) api.on("get", `${BASE}/${plan.id}`, () => plan);
  api.on("get", `${BASE}/7/narrative`, () => vanNarrative());
  api.on("get", `${BASE}/8/narrative`, () => vanNarrative({ plan_id: 8 }));
}

describe("VanRoutesPage", () => {
  beforeEach(() => {
    api.reset();
    useToastStore.setState({ toasts: [] });
    signIn("distributor");
  });

  it("opens the pending plan: map, stops, savings, fairness and the explanation", async () => {
    serve(vanPlan());
    open();
    expect(screen.getByTestId("van-skeleton")).toBeInTheDocument();
    expect(await screen.findByTestId("stub-map")).toBeInTheDocument();
    expect(screen.getAllByTestId("van-stop")).toHaveLength(5);
    expect(screen.getByTestId("savings-panel")).toBeInTheDocument();
    expect(screen.getByTestId("fairness-panel")).toBeInTheDocument();
    expect(await screen.findByTestId("narrative")).toHaveTextContent("Van 1 serves two shops first");
    expect(screen.getByTestId("plan-status")).toHaveTextContent("Waiting for your decision");
    expect(api.get).toHaveBeenCalledWith(BASE, { params: { status: "pending", page_size: 1 } });
  });

  it("opens the plan named in the URL without asking for the pending one", async () => {
    serve(vanPlan({ status: "approved", decided_at: "2026-03-10T07:00:00Z", note: "Approved after check" }));
    open("/distributor/van-routes?plan=7");
    expect(await screen.findByTestId("plan-decision")).toHaveTextContent("Approved after check");
    // A decided plan cannot be decided again.
    expect(screen.queryByTestId("van-decide")).not.toBeInTheDocument();
  });

  it("shows the empty state and creates the first plan", async () => {
    serve(null);
    api.on("post", BASE, () => vanPlan());
    api.on("get", `${BASE}/7`, () => vanPlan());
    open();
    expect(await screen.findByText("No plan yet")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create plan" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(BASE, {}));
    expect(await screen.findByTestId("stub-map")).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent("plan=7");
  });

  it("says when no agent needs a van", async () => {
    serve(vanPlan({ routes: [], unrouted: [], served: 0, dropped: 0, trips: 0, km: 0 }));
    open();
    expect(await screen.findByText("No agent needs a van right now")).toBeInTheDocument();
    expect(screen.queryByTestId("stub-map")).not.toBeInTheDocument();
  });

  it("shows an error with a retry when the plan cannot be loaded", async () => {
    let calls = 0;
    api.on("get", BASE, () => {
      calls += 1;
      if (calls === 1) throw new Error("network");
      return vanPage([vanPlan()]);
    });
    api.on("get", `${BASE}/7`, () => vanPlan());
    api.on("get", `${BASE}/7/narrative`, () => vanNarrative());
    open();
    fireEvent.click(await screen.findByRole("button", { name: /try again/i }));
    expect(await screen.findByTestId("stub-map")).toBeInTheDocument();
  });

  it("solves again a moment after the vans change", async () => {
    serve(vanPlan());
    api.on("post", BASE, () => vanPlan({ id: 8, params: { config: { vehicles: 3, capacity_bdt: 1_500_000, cash_cap_bdt: 1_500_000 } } }));
    api.on("get", `${BASE}/8`, () => vanPlan({ id: 8 }));
    open();
    await screen.findByTestId("stub-map");
    fireEvent.click(screen.getByTestId("vans-inc"));
    expect(screen.getByTestId("vans-count")).toHaveTextContent("3");
    expect(api.post).not.toHaveBeenCalled();
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(BASE, { vehicles: { count: 3, capacity_bdt: 1_500_000, cash_cap_bdt: 1_500_000 } }), { timeout: 2500 });
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("plan=8"));
    expect(screen.getByTestId("van-routes-page")).toHaveAttribute("data-plan-id", "8");
  });

  it("tells the user when forecasts are not ready", async () => {
    serve(null);
    api.on("post", BASE, () => {
      throw Object.assign(new Error("503"), { isAxiosError: true, response: { status: 503, data: { detail: "van_not_ready" } } });
    });
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Create plan" }));
    await waitFor(() => expect(useToastStore.getState().toasts.map((t) => t.title)).toContain("Forecasts are not ready yet. Try again in a minute."));
  });

  it("switches the map between optimised routes and separate trips", async () => {
    serve(vanPlan());
    open();
    expect(await screen.findByTestId("stub-map")).toHaveAttribute("data-view", "optimised");
    fireEvent.click(screen.getByRole("radio", { name: "Separate trips" }));
    expect(screen.getByTestId("stub-map")).toHaveAttribute("data-view", "separate");
  });

  it("keeps the map and the stop list in step on selection", async () => {
    serve(vanPlan());
    open();
    const map = await screen.findByTestId("stub-map");
    fireEvent.click(map);
    expect(map).toHaveAttribute("data-selected", "2");
    expect(screen.getAllByTestId("van-stop").find((r) => r.getAttribute("data-stop-id") === "2")).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getAllByTestId("van-stop")[0] as HTMLElement);
    expect(map).toHaveAttribute("data-selected", "1");
  });

  it("approves with a note and keeps showing the decided plan", async () => {
    serve(vanPlan());
    api.on("post", `${BASE}/7/decision`, () => vanPlan({ status: "approved", decided_at: "2026-03-10T07:00:00Z", note: "Vans are free today" }));
    open();
    await screen.findByTestId("stub-map");
    fireEvent.click(screen.getByTestId("van-decide"));
    const dialog = await screen.findByTestId("van-approve-dialog");
    expect(within(dialog).getByTestId("van-approve")).toBeDisabled();
    fireEvent.change(within(dialog).getByTestId("van-note"), { target: { value: "Vans are free today" } });
    fireEvent.click(within(dialog).getByTestId("van-approve"));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${BASE}/7/decision`, { decision: "approve", note: "Vans are free today" }));
    await waitFor(() => expect(screen.getByTestId("plan-status")).toHaveTextContent("Approved"));
    expect(screen.getByTestId("location")).toHaveTextContent("plan=7");
    expect(screen.queryByTestId("van-decide")).not.toBeInTheDocument();
    expect(screen.getByTestId("stub-map")).toBeInTheDocument();
  });
});
