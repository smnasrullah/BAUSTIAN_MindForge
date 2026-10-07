import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchSystemStatus, type SystemStatus } from "../../lib/systemStatus";
import { BootstrapGate } from "./BootstrapGate";

vi.mock("../../lib/systemStatus", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../lib/systemStatus")>()),
  fetchSystemStatus: vi.fn(),
}));

const base: SystemStatus = {
  ready: false,
  bootstrap_state: "seeding",
  db: true,
  migration_current: "0001",
  migration_head: "0001",
  seed: 42,
  data_version: "0.1.0",
  artifacts_ok: false,
  model_version: null,
  llm_mode: "template",
  demo_mode: true,
  dev_mailer: true,
  generated_at: "2026-10-01T00:00:00Z",
};

function renderGate() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BootstrapGate>
        <p>App content</p>
      </BootstrapGate>
    </QueryClientProvider>,
  );
}

describe("BootstrapGate", () => {
  beforeEach(() => vi.mocked(fetchSystemStatus).mockReset());

  it("shows the preparing screen while bootstrap is running", async () => {
    vi.mocked(fetchSystemStatus).mockResolvedValue(base);
    renderGate();
    expect(await screen.findByText("Preparing demo data…")).toBeInTheDocument();
    expect(screen.queryByText("App content")).not.toBeInTheDocument();
  });

  it("renders the app once the system is ready", async () => {
    vi.mocked(fetchSystemStatus).mockResolvedValue({ ...base, ready: true, bootstrap_state: "ready" });
    renderGate();
    expect(await screen.findByText("App content")).toBeInTheDocument();
  });

  it("shows neither the app nor the preparing screen before the first status answer", async () => {
    let answer: (s: SystemStatus) => void = () => undefined;
    vi.mocked(fetchSystemStatus).mockReturnValue(new Promise<SystemStatus>((r) => (answer = r)));
    renderGate();
    expect(screen.queryByText("App content")).not.toBeInTheDocument();
    expect(screen.queryByText(/First start/)).not.toBeInTheDocument();
    expect(screen.queryByText("Preparing demo data…")).not.toBeInTheDocument();
    answer({ ...base, ready: true, bootstrap_state: "ready" });
    expect(await screen.findByText("App content")).toBeInTheDocument();
  });

  it("shows a failure message when bootstrap failed", async () => {
    vi.mocked(fetchSystemStatus).mockResolvedValue({ ...base, bootstrap_state: "failed" });
    renderGate();
    expect(await screen.findByText("Setup stopped")).toBeInTheDocument();
  });
});
