import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ClockInfo, Freshness } from "../../api/types";
import { api as realApi } from "../../lib/api";
import type { FakeApi } from "../../test/fakeApi";
import { signIn } from "../../features/auth/testUtils";
import { renderAt } from "../../features/distributor/testRender";
import { FreshnessChip } from "./FreshnessChip";

vi.mock("../../lib/api", async () => {
  const { createFakeApi } = await import("../../test/fakeApi");
  return { api: createFakeApi(), authClient: { post: vi.fn() }, refreshAccessToken: vi.fn() };
});

const api = realApi as unknown as FakeApi;

function freshness(clock: ClockInfo | null): Freshness {
  const now = new Date();
  return {
    generated_at: now.toISOString(),
    last_forecast_at: new Date(now.getTime() - 2 * 60_000).toISOString(),
    llm_mode: "template",
    model_version: "v3",
    data_period: { start: "2026-06-07T00:00:00+06:00", end: now.toISOString(), holdout_start: "2026-09-21T00:00:00+06:00", sim_now: now.toISOString() },
    clock,
  };
}

const LIVE: ClockInfo = {
  mode: "live",
  timezone: "Asia/Dhaka",
  now: new Date().toISOString(),
  data_hour: new Date().toISOString(),
  last_data_hour: new Date().toISOString(),
  last_compute_at: new Date().toISOString(),
};

describe("freshness chip", () => {
  beforeEach(() => {
    api.reset();
    signIn("agent");
  });

  it("labels the live clock honestly and keeps 'Updated' tied to the last compute", async () => {
    api.on("get", "/system/freshness", () => freshness(LIVE));
    renderAt("/agent", "/agent", <FreshnessChip />);
    const chip = await screen.findByTestId("freshness-chip");
    expect(chip).toHaveTextContent("Live simulation (synthetic data) · Updated 2m ago · model v3");
    expect(chip).toHaveAttribute("data-clock-mode", "live");
  });

  it("says when the fixed benchmark clock is in use", async () => {
    api.on("get", "/system/freshness", () => freshness({ ...LIVE, mode: "fixed" }));
    renderAt("/agent", "/agent", <FreshnessChip />);
    expect(await screen.findByTestId("freshness-chip")).toHaveTextContent(/^Fixed clock \(synthetic data\) · Updated/);
  });

  it("still works when the server sends no clock block", async () => {
    api.on("get", "/system/freshness", () => freshness(null));
    renderAt("/agent", "/agent", <FreshnessChip />);
    const chip = await screen.findByTestId("freshness-chip");
    expect(chip).toHaveTextContent(/^Updated 2m ago · model v3$/);
    expect(chip).toHaveAttribute("data-clock-mode", "unknown");
  });
});
