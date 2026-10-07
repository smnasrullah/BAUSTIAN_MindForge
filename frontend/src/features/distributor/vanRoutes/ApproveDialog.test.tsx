import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useToastStore, type Toast } from "../../../components/ui/toastStore";
import { api as realApi } from "../../../lib/api";
import type { FakeApi } from "../../../test/fakeApi";
import { renderAt } from "../testRender";
import { ApproveDialog } from "./ApproveDialog";
import { vanPlan } from "./testFixtures";

vi.mock("../../../lib/api", async () => {
  const { createFakeApi } = await import("../../../test/fakeApi");
  return { api: createFakeApi(), authClient: { post: vi.fn() }, refreshAccessToken: vi.fn() };
});

const api = realApi as unknown as FakeApi;
const PATH = "/distributor/van-plans/7/decision";

function show(onOpenChange = vi.fn(), onDecided = vi.fn()) {
  renderAt("/", "/", <ApproveDialog plan={vanPlan()} open onOpenChange={onOpenChange} onDecided={onDecided} />);
  return { onOpenChange, onDecided };
}

describe("ApproveDialog", () => {
  beforeEach(() => {
    api.reset();
    useToastStore.setState({ toasts: [] });
    api.on("post", PATH, (body) => vanPlan({ status: (body as { decision: string }).decision === "approve" ? "approved" : "rejected" }));
  });

  it("summarises the plan and keeps both decisions off until a note is written", () => {
    show();
    const dialog = screen.getByTestId("van-approve-dialog");
    expect(within(dialog).getByTestId("van-approve-summary")).toHaveTextContent("2 vans, 3 stops, 31.5 km, total cost ৳9.8k");
    expect(within(dialog).getByTestId("van-approve")).toBeDisabled();
    expect(within(dialog).getByTestId("van-reject")).toBeDisabled();
    fireEvent.change(within(dialog).getByTestId("van-note"), { target: { value: "ok" } });
    expect(within(dialog).getByTestId("van-approve")).toBeDisabled();
    fireEvent.change(within(dialog).getByTestId("van-note"), { target: { value: "Vans are free today" } });
    expect(within(dialog).getByTestId("van-approve")).toBeEnabled();
    expect(within(dialog).getByTestId("van-reject")).toBeEnabled();
  });

  it("approves with the trimmed note, tells the page, and closes", async () => {
    const { onOpenChange, onDecided } = show();
    fireEvent.change(screen.getByTestId("van-note"), { target: { value: "  Vans are free today  " } });
    fireEvent.click(screen.getByTestId("van-approve"));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(PATH, { decision: "approve", note: "Vans are free today" }));
    await waitFor(() => expect(onDecided).toHaveBeenCalledWith(7));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(useToastStore.getState().toasts.map((t: Toast) => t.title)).toContain("Plan approved");
  });

  it("rejects with a note", async () => {
    const { onDecided } = show();
    fireEvent.change(screen.getByTestId("van-note"), { target: { value: "Too far for one shift" } });
    fireEvent.click(screen.getByTestId("van-reject"));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(PATH, { decision: "reject", note: "Too far for one shift" }));
    await waitFor(() => expect(useToastStore.getState().toasts.map((t: Toast) => t.title)).toContain("Plan rejected"));
    expect(onDecided).toHaveBeenCalledWith(7);
  });

  it("keeps the dialog open and says so when the decision cannot be saved", async () => {
    api.on("post", PATH, () => {
      throw new Error("network");
    });
    const { onOpenChange, onDecided } = show();
    fireEvent.change(screen.getByTestId("van-note"), { target: { value: "Vans are free today" } });
    fireEvent.click(screen.getByTestId("van-approve"));
    await waitFor(() => expect(useToastStore.getState().toasts.map((t: Toast) => t.title)).toContain("Could not save your decision. Try again."));
    expect(onDecided).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalled();
  });
});
