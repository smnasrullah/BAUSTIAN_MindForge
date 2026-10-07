// Own file: in BootstrapGate.test.tsx the same failing status mock was reported as a test error
// (vitest module-mock quirk); here it behaves like the real network failure it stands for.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { fetchSystemStatus } from "../../lib/systemStatus";
import { BootstrapGate } from "./BootstrapGate";

vi.mock("../../lib/systemStatus", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../lib/systemStatus")>()),
  fetchSystemStatus: vi.fn(),
}));

it("shows the preparing screen when the backend cannot be reached", async () => {
  vi.mocked(fetchSystemStatus).mockImplementation(() => Promise.reject(new Error("offline")));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <BootstrapGate>
        <p>App content</p>
      </BootstrapGate>
    </QueryClientProvider>,
  );
  expect(await screen.findByText("Preparing demo data…")).toBeInTheDocument();
  expect(screen.queryByText("App content")).not.toBeInTheDocument();
});
