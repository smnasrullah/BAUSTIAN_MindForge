import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api as realApi } from "../../lib/api";
import type { FakeApi } from "../../test/fakeApi";
import { qk } from "../keys";
import type { NotificationListQuery, NotificationPage } from "../types";
import { useHelpUnread, useNotifications } from "./notifications";

vi.mock("../../lib/api", async () => {
  const { createFakeApi } = await import("../../test/fakeApi");
  return { api: createFakeApi(), authClient: { post: vi.fn() }, refreshAccessToken: vi.fn() };
});

const api = realApi as unknown as FakeApi;

function page(unread: number): NotificationPage {
  return { items: [], page: 1, page_size: 20, total: 0, unread_count: unread };
}

function listCalls(): number {
  return api.get.mock.calls.filter(([, cfg]) => {
    const params = (cfg as { params?: NotificationListQuery } | undefined)?.params;
    return params?.entity_type === undefined;
  }).length;
}

function Bell(): null {
  useNotifications({ page_size: 20 });
  useHelpUnread();
  return null;
}

function Nav(): null {
  useHelpUnread();
  return null;
}

let client = new QueryClient();

function wrap(children: ReactNode) {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

afterEach(() => api.reset());

describe("useHelpUnread", () => {
  it("refetches the lists on a rise in unread help, not on the first answer", async () => {
    let unread = 3;
    api.on("get", "/notifications", () => page(unread));
    render(wrap(<><Bell /><Nav /></>));
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2)); // list + one shared help poll
    await new Promise((r) => setTimeout(r, 50));
    expect(listCalls()).toBe(1);

    // A real rise (a new help request) refreshes the list once, though two components watch it.
    unread = 4;
    await client.refetchQueries({ queryKey: qk.notifications.list({ entity_type: "liquidity_request", unread: true, page_size: 1 }) });
    await waitFor(() => expect(listCalls()).toBe(2));
    await new Promise((r) => setTimeout(r, 50));
    expect(listCalls()).toBe(2);
  });
});
