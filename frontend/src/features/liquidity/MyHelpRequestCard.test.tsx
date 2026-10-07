import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { HelpRequestItem } from "../../api/types";
import { useToastStore } from "../../components/ui/toastStore";
import { api as realApi } from "../../lib/api";
import type { FakeApi } from "../../test/fakeApi";
import { MyHelpRequestCard } from "./MyHelpRequestCard";

vi.mock("../../lib/api", async () => {
  const { createFakeApi } = await import("../../test/fakeApi");
  return { api: createFakeApi(), authClient: { post: vi.fn() }, refreshAccessToken: vi.fn() };
});

const api = realApi as unknown as FakeApi;
const NOW = new Date("2026-03-10T07:40:00Z");

function recipient(display: string, response: "accepted" | "declined" | "none", wave = 1) {
  return {
    user_id: `00000000-0000-0000-0000-00000000000${display.slice(-1)}`,
    display,
    role: "agent" as const,
    wave_number: wave,
    response,
    notified_at: null,
    responded_at: null,
    distance_km: 1.1,
  };
}

function mine(over: Partial<HelpRequestItem> = {}): HelpRequestItem {
  return {
    id: 7,
    view: "owner",
    requester: { agent_id: 1, code: "AGT-0001", name: "Mirpur 10 Mobile Point", upazila: "Mirpur", district: "Dhaka" },
    float_type: "emoney",
    amount_needed: 15000,
    needed_by: "2026-03-10T09:40:00Z",
    status: "open",
    wave_number: 1,
    created_by: "system",
    created_at: "2026-03-10T06:00:00Z",
    updated_at: "2026-03-10T06:00:00Z",
    claimed_at: null,
    claim_expires_at: null,
    fulfilled_at: null,
    my_response: null,
    claimed_by_me: false,
    my_distance_km: null,
    simulated: false,
    reason_summary: "Cash runs out in 3 hours",
    claimed_by: null,
    recipients: [recipient("AGT-0009", "none"), recipient("AGT-0010", "declined", 2)],
    advisory: true,
    urgent: false,
    deadline_asap: false,
    reason_category: "unknown",
    can_confirm_late: false,
    ...over,
  };
}

function renderCard(card: HelpRequestItem) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MyHelpRequestCard item={card} now={NOW} />
    </QueryClientProvider>,
  );
}

describe("MyHelpRequestCard", () => {
  beforeEach(() => {
    api.reset();
    useToastStore.setState({ toasts: [] });
  });

  it("shows the status, time left and how many were asked, never their names", () => {
    renderCard(mine());
    const card = screen.getByTestId("my-help-request");
    expect(screen.getByTestId("my-help-status")).toHaveTextContent("Waiting for a helper");
    expect(screen.getByTestId("my-help-left")).toHaveTextContent("left");
    expect(screen.getByTestId("my-help-asked")).toHaveTextContent("2 nearby helpers were asked");
    expect(card).not.toHaveTextContent("AGT-0009");
    expect(card).not.toHaveTextContent("AGT-0010");
  });

  it("marks the first step current while nobody has accepted yet", () => {
    renderCard(mine());
    const steps = screen.getByTestId("help-timeline");
    expect(within(steps).getByText("Someone accepted").closest("li")).toHaveAttribute("data-state", "current");
    expect(screen.queryByRole("button", { name: "I received the money" })).not.toBeInTheDocument();
  });

  it("offers the money-received button once someone accepted, and confirms it", async () => {
    api.on("post", "/liquidity-requests/7/confirm", () => mine({ status: "fulfilled" }));
    renderCard(mine({ status: "claimed" }));
    expect(screen.getByTestId("my-help-status")).toHaveTextContent("A helper said yes");

    fireEvent.click(screen.getByRole("button", { name: "I received the money" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/liquidity-requests/7/confirm", {}));
    await waitFor(() => expect(useToastStore.getState().toasts[0]?.title).toBe("Thank you. The request is marked as received."));
  });

  it("asks before cancelling, then cancels", async () => {
    api.on("post", "/liquidity-requests/7/cancel", () => mine({ status: "cancelled" }));
    renderCard(mine());

    fireEvent.click(screen.getByRole("button", { name: "Cancel request" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Cancel this request?");
    expect(api.post).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel request" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/liquidity-requests/7/cancel", {}));
  });

  it("shows the requester their own full reason and the Urgent badge", () => {
    renderCard(mine({ urgent: true, reason_summary: "ক্যাশ প্রায় ৩ ঘণ্টায় শেষ হবে (বেতনের দিন)।" }));
    expect(screen.getByTestId("help-urgent")).toHaveTextContent("Urgent");
    const reason = screen.getByTestId("my-help-reason");
    expect(reason).toHaveTextContent("বেতনের দিন");
    expect(reason.querySelector('[lang="bn"]')).not.toBeNull();
  });
});
