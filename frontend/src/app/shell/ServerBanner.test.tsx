import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { AxiosError, AxiosHeaders } from "axios";
import { describe, expect, it, vi } from "vitest";

import { api as realApi } from "../../lib/api";
import { isServerUnreachable, useServerHealth } from "../../lib/serverHealth";
import type { FakeApi } from "../../test/fakeApi";
import { ServerBanner } from "./ServerBanner";

vi.mock("../../lib/api", async () => {
  const { createFakeApi } = await import("../../test/fakeApi");
  return { api: createFakeApi(), authClient: { post: vi.fn() }, refreshAccessToken: vi.fn() };
});

const api = realApi as unknown as FakeApi;

function axiosError(status?: number, code?: string): AxiosError {
  const config = { headers: new AxiosHeaders() };
  const response = status === undefined ? undefined : { status, statusText: "", headers: {}, config, data: {} };
  return new AxiosError("failed", code, config, undefined, response);
}

describe("server reachability", () => {
  it("counts network errors and gateway errors, not answers from the app", () => {
    expect(isServerUnreachable(axiosError())).toBe(true);
    expect(isServerUnreachable(axiosError(502))).toBe(true);
    expect(isServerUnreachable(axiosError(503))).toBe(true);
    expect(isServerUnreachable(axiosError(500))).toBe(false);
    expect(isServerUnreachable(axiosError(401))).toBe(false);
    expect(isServerUnreachable(axiosError(undefined, "ERR_CANCELED"))).toBe(false);
    expect(isServerUnreachable(new Error("boom"))).toBe(false);
  });

  it("the banner says reconnecting, pings the server, then says reconnected", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    api.on("get", "/system/health", () => {
      act(() => useServerHealth.getState().markUp());
      return { status: "ok" };
    });
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <ServerBanner />
      </QueryClientProvider>,
    );
    expect(screen.queryByText("Lost contact with the server. Reconnecting…")).not.toBeInTheDocument();
    act(() => useServerHealth.getState().markDown());
    expect(await screen.findByText("Lost contact with the server. Reconnecting…")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(3000));
    expect(api.get).toHaveBeenCalledWith("/system/health");
    await waitFor(() => expect(screen.getByText("Reconnected. Refreshing data.")).toBeInTheDocument());
    vi.useRealTimers();
  });
});
