import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { refreshAccessToken } from "../../lib/api";
import { AuthBootstrap } from "./AuthBootstrap";
import { useAuthStore } from "./authStore";

vi.mock("../../lib/api", () => ({ refreshAccessToken: vi.fn() }));

const SESSION = {
  access_token: "a",
  token_type: "bearer" as const,
  expires_in: 900,
  user: { id: "u1", email: "d@x.org", full_name: "D", role: "distributor" as const, agent_id: null, distributor_id: 1 },
};

describe("AuthBootstrap", () => {
  afterEach(() => vi.useRealTimers());

  it("keeps checking when the server cannot be reached, then restores the session", async () => {
    act(() => useAuthStore.setState({ status: "checking", accessToken: null, user: null, notice: null }));
    let calls = 0;
    vi.mocked(refreshAccessToken).mockImplementation(async () => {
      calls += 1;
      if (calls < 3) return null; // network error: the store stays "checking"
      act(() => useAuthStore.getState().setSession(SESSION as never));
      return "a";
    });
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(
      <AuthBootstrap>
        <p>App</p>
      </AuthBootstrap>,
    );
    expect(await screen.findByText("Cannot reach the server. Trying again…")).toBeInTheDocument();
    expect(useAuthStore.getState().status).toBe("checking");
    await act(() => vi.advanceTimersByTimeAsync(1000));
    await act(() => vi.advanceTimersByTimeAsync(2000));
    await waitFor(() => expect(screen.getByText("App")).toBeInTheDocument());
    expect(calls).toBe(3);
    expect(useAuthStore.getState().status).toBe("signedIn");
  });

  it("a rejected check shows the app (signed out) at once, without retrying", async () => {
    act(() => useAuthStore.setState({ status: "checking", accessToken: null, user: null, notice: null }));
    vi.mocked(refreshAccessToken).mockImplementation(async () => {
      act(() => useAuthStore.getState().signOut(null));
      return null;
    });
    render(
      <AuthBootstrap>
        <p>App</p>
      </AuthBootstrap>,
    );
    expect(await screen.findByText("App")).toBeInTheDocument();
    expect(refreshAccessToken).toHaveBeenCalledTimes(1);
  });
});
