import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PainPoints } from "../../../api/types";
import { api as realApi } from "../../../lib/api";
import type { FakeApi } from "../../../test/fakeApi";
import { signIn } from "../../auth/testUtils";
import { renderAt } from "../testRender";
import { DiscoveryPage } from "./DiscoveryPage";

vi.mock("../../../lib/api", async () => {
  const { createFakeApi } = await import("../../../test/fakeApi");
  return { api: createFakeApi(), authClient: { post: vi.fn() }, refreshAccessToken: vi.fn() };
});

const api = realApi as unknown as FakeApi;

const DATA: PainPoints = {
  field_interviews_count: 0,
  pain_points: [
    { tag: "cash_shortage", label_en: "Cash runs out", label_bn: "ক্যাশ শেষ", field_count: 0, literature_count: 1, simulated_count: 1, feature_en: "Dual-float forecast", feature_bn: "পূর্বাভাস", feature_route: "/agent/stockout" },
  ],
  literature: [{ source: "Mondato", year_note: "three countries", fact: "Demand is hard to predict.", tags: ["cash_shortage"] }],
  personas: [{ id: "P1", title_en: "Rural agent", title_bn: "গ্রামের এজেন্ট", hypothesis_en: "Runs out of cash first.", hypothesis_bn: "ক্যাশ আগে শেষ।", tags: ["cash_shortage"], source_ref: null, label: "SIMULATED" }],
  incidence: {
    note: "stress test", seed: 42, agents: 300, date: "2026-10-07",
    rows: [{ buffer_factor: 1, baseline_stockout_hours: 322, baseline_share: 0.00319, ai_stockout_hours: 75, ai_share: 0.00074, hours_avoided: 247, percent_reduction: 0.767, value_saved_bdt: 2054730, van_trips_avoided: -292 }],
  },
};

describe("discovery", () => {
  beforeEach(() => {
    api.reset();
    signIn("distributor");
    api.on("get", "/evidence/pain-points", () => DATA);
  });

  it("says no field interviews yet and labels simulated items", async () => {
    renderAt("/distributor/discovery", "/distributor/discovery", <DiscoveryPage />);
    expect(await screen.findByText("No field interviews yet")).toBeInTheDocument();
    const row = screen.getByTestId("pain-point");
    expect(within(row).getByTestId("chip-FIELD")).toHaveTextContent("0");
    expect(within(row).getByTestId("chip-SIMULATED")).toHaveTextContent("1");
    expect(screen.getByText("Dual-float forecast")).toBeInTheDocument();
    expect(screen.getByTestId("incidence-table")).toHaveTextContent("322");
  });
});
