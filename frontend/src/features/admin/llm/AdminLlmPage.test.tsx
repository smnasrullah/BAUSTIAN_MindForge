import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api as realApi } from "../../../lib/api";
import type { FakeApi } from "../../../test/fakeApi";
import { signIn } from "../../auth/testUtils";
import { renderAt } from "../../distributor/testRender";
import { llmLog, llmStatus, llmUsage } from "../testFixtures";
import { AdminLlmPage } from "./AdminLlmPage";
import { dayBars } from "./usageModel";

vi.mock("../../../lib/api", async () => {
  const { createFakeApi } = await import("../../../test/fakeApi");
  return { api: createFakeApi(), authClient: { post: vi.fn() }, refreshAccessToken: vi.fn() };
});

const api = realApi as unknown as FakeApi;

describe("admin LLM page", () => {
  beforeEach(() => {
    api.reset();
    signIn("admin");
    api.on("get", "/llm/status", () => llmStatus());
    api.on("get", "/admin/llm/usage", () => llmUsage());
    api.on("get", "/admin/llm/logs", () => ({
      items: [llmLog(), llmLog({ id: 8, provider: "anthropic", model: "claude-haiku-4-5", cache_hit: false, generated_by: "template", guard_result: "numbers_fail", prompt_tokens: 420, completion_tokens: 96, latency_ms: 1180 })],
      total: 2,
      page: 1,
      page_size: 50,
    }));
    api.on("get", "/admin/drift", () => ({
      model_version: "lgbq-1.0.0-56571e7f",
      origin: "2026-04-30T14:00:00Z",
      watch_ratio: 1.2,
      drift_ratio: 1.5,
      status: "watch",
      generated_at: "2026-10-03T08:00:00Z",
      floats: [
        {
          float_type: "cash",
          status: "watch",
          hours_compared: 21600,
          by_horizon: [
            { horizon_h: 1, mae: 2100 },
            { horizon_h: 2, mae: 2300 },
          ],
          buckets: [
            { horizon: "1-6", mae: 2900, reference_mae: 2394.66, ratio: 1.211, status: "watch" },
            { horizon: "7-24", mae: 2000, reference_mae: 2078, ratio: 0.962, status: "stable" },
          ],
        },
      ],
    }));
  });

  it("says why recorded answers are skipped on the live clock", async () => {
    api.on("get", "/llm/status", () => ({ ...llmStatus(), mode: "template", replay_skipped: "live_clock" }));
    renderAt("/admin/llm", "/admin/llm", <AdminLlmPage />);
    expect(await screen.findByTestId("replay-row")).toHaveTextContent(/Skipped: the live clock.*CLOCK_MODE=fixed/);
  });

  it("splits each day's calls into disjoint parts", () => {
    expect(dayBars(llmUsage())[1]?.parts).toEqual({ live: 2, cache: 1, replay: 0, template: 1 });
  });

  it("shows status, cap usage, the call log and drift", async () => {
    renderAt("/admin/llm", "/admin/llm", <AdminLlmPage />);
    const cap = await screen.findByTestId("llm-cap");
    expect(within(cap).getByRole("meter")).toHaveAttribute("aria-valuenow", "400");
    expect(within(cap).getByText("400 of 500 live calls since 00:00 UTC")).toBeInTheDocument();
    const log = within(await screen.findByTestId("llm-log")).getByRole("table");
    expect(await within(log).findByText("Numbers mismatch")).toBeInTheDocument();
    expect(within(log).getByText("420 / 96")).toBeInTheDocument();
    expect(within(log).getByText("Hit")).toBeInTheDocument();
    const drift = await screen.findByTestId("drift-panel");
    expect(await within(drift).findAllByText("Watch")).not.toHaveLength(0);
    expect(within(drift).getByText("×1.21")).toBeInTheDocument();
    expect(within(await screen.findByTestId("llm-provider")).getByText("Not set")).toBeInTheDocument();
  });

  it("filters the call log through the URL", async () => {
    renderAt("/admin/llm", "/admin/llm", <AdminLlmPage />);
    await screen.findByTestId("llm-log");
    fireEvent.change(screen.getByLabelText("Guard result"), { target: { value: "numbers_fail" } });
    fireEvent.change(screen.getByLabelText("Cache"), { target: { value: "miss" } });
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("guard=numbers_fail&cache=miss"));
    expect(api.get).toHaveBeenLastCalledWith("/admin/llm/logs", { params: { guard_result: "numbers_fail", cache_hit: false, page: 1, page_size: 50 } });
  });
});
