import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminClock } from "../../../api/types";
import { useToastStore } from "../../../components/ui/toastStore";
import { api as realApi } from "../../../lib/api";
import type { FakeApi } from "../../../test/fakeApi";
import { signIn } from "../../auth/testUtils";
import { renderAt } from "../../distributor/testRender";
import { DataClockPanel } from "./DataClockPanel";

vi.mock("../../../lib/api", async () => {
  const { createFakeApi } = await import("../../../test/fakeApi");
  return { api: createFakeApi(), authClient: { post: vi.fn() }, refreshAccessToken: vi.fn() };
});

const api = realApi as unknown as FakeApi;

const LIVE: AdminClock = {
  clock: {
    mode: "live",
    timezone: "Asia/Dhaka",
    now: "2026-10-05T05:07:00Z",
    data_hour: "2026-10-05T05:00:00Z",
    last_data_hour: "2026-10-05T04:00:00Z",
    last_compute_at: "2026-10-05T05:00:40Z",
  },
  tick_interval_s: 30,
  budget_s: 60,
  next_tick_at: "2026-10-05T06:00:00Z",
  last_tick: {
    reason: "hourly",
    started_at: "2026-10-05T05:00:05Z",
    from_hour: "2026-10-05T04:00:00Z",
    to_hour: "2026-10-05T05:00:00Z",
    hours: 1,
    regenerated: null,
    story_reanchored: false,
    precomputed: true,
    duration_s: 31.4,
    stages: [{ name: "forecast", seconds: 12.1 }],
  },
  over_budget: false,
  catchup: null,
  last_error: null,
  last_error_at: null,
  tick_requested_at: null,
  demo_story: { agent_code: "AGT-0001", refill_at: "2026-10-05T05:00:00Z", stockout_at: "2026-10-05T09:40:00Z", demo_event: "Demo event" },
  generated_at: "2026-10-05T05:07:00Z",
  skipped_ticks: 0,
  last_skipped_at: null,
};

describe("data clock card", () => {
  beforeEach(() => {
    api.reset();
    useToastStore.setState({ toasts: [] });
    signIn("admin");
  });

  it("shows the live clock, the last tick and the demo story", async () => {
    api.on("get", "/admin/clock", () => LIVE);
    renderAt("/admin", "/admin", <DataClockPanel />);
    const card = await screen.findByTestId("data-clock-panel");
    expect(within(card).getByTestId("clock-mode")).toHaveTextContent("Live");
    expect(within(card).getByText("Live simulation (synthetic data)")).toBeInTheDocument();
    expect(within(card).getByText("1 h of data · 31.4 s")).toBeInTheDocument();
    expect(within(card).getByText(/AGT-0001 runs out of cash/)).toBeInTheDocument();
    expect(within(card).getByText("labelled demo event")).toBeInTheDocument();
    expect(within(card).getByText("Up to date")).toBeInTheDocument();
    expect(within(card).getByTestId("clock-backtest")).toHaveTextContent("Not run yet");
  });

  it("shows the daily backtest job as its own line, and skipped ticks", async () => {
    api.on("get", "/admin/clock", () => ({
      ...LIVE,
      backtest: {
        state: "ok",
        started_at: "2026-10-04T18:00:20Z",
        last_run_at: "2026-10-04T18:00:20Z",
        duration_s: 44.2,
        budget_s: 180,
        over_budget: false,
        last_error: null,
      },
      skipped_ticks: 1,
      last_skipped_at: "2026-10-05T05:00:30Z",
    }));
    renderAt("/admin", "/admin", <DataClockPanel />);
    const card = await screen.findByTestId("data-clock-panel");
    expect(within(card).getByText("Impact backtest")).toBeInTheDocument();
    expect(within(card).getByTestId("clock-backtest")).toHaveTextContent("Done in 44.2 s");
    expect(within(card).getByText("1 tick(s) skipped: the previous tick was still running")).toBeInTheDocument();
  });

  it("flags a failed backtest run", async () => {
    api.on("get", "/admin/clock", () => ({
      ...LIVE,
      backtest: {
        state: "failed",
        started_at: "2026-10-04T18:00:20Z",
        last_run_at: "2026-10-04T18:00:20Z",
        duration_s: 3,
        budget_s: 180,
        over_budget: false,
        last_error: "RuntimeError: x",
      },
    }));
    renderAt("/admin", "/admin", <DataClockPanel />);
    expect(await screen.findByText("Failed after 3.0 s")).toBeInTheDocument();
  });

  it("asks the server for a tick now", async () => {
    let posted = 0;
    api.on("get", "/admin/clock", () => LIVE);
    api.on("post", "/admin/clock/tick", () => {
      posted += 1;
      return { requested_at: "2026-10-05T05:08:00Z" };
    });
    renderAt("/admin", "/admin", <DataClockPanel />);
    fireEvent.click(await screen.findByTestId("run-tick"));
    await waitFor(() => expect(posted).toBe(1));
    await waitFor(() => expect(useToastStore.getState().toasts.map((t) => t.title)).toContain("Tick requested. The leader process runs it within a minute."));
  });

  it("hides the tick button on the fixed clock", async () => {
    api.on("get", "/admin/clock", () => ({ ...LIVE, clock: { ...LIVE.clock, mode: "fixed" }, next_tick_at: null, demo_story: null }));
    renderAt("/admin", "/admin", <DataClockPanel />);
    const card = await screen.findByTestId("data-clock-panel");
    expect(within(card).getByTestId("clock-mode")).toHaveTextContent("Fixed");
    expect(within(card).queryByTestId("run-tick")).not.toBeInTheDocument();
    expect(within(card).getByText("None ahead")).toBeInTheDocument();
    expect(within(card).queryByText("Impact backtest")).not.toBeInTheDocument();
  });

  it("offers a retry when the card cannot load", async () => {
    api.on("get", "/admin/clock", () => {
      throw new Error("down");
    });
    renderAt("/admin", "/admin", <DataClockPanel />);
    expect(await screen.findByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
