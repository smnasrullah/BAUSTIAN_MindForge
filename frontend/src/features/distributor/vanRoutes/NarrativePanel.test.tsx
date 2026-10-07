import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api as realApi } from "../../../lib/api";
import type { FakeApi } from "../../../test/fakeApi";
import { renderAt } from "../testRender";
import { NarrativePanel } from "./NarrativePanel";
import { vanNarrative } from "./testFixtures";

vi.mock("../../../lib/api", async () => {
  const { createFakeApi } = await import("../../../test/fakeApi");
  return { api: createFakeApi(), authClient: { post: vi.fn() }, refreshAccessToken: vi.fn() };
});

const api = realApi as unknown as FakeApi;
const PATH = "/distributor/van-plans/7/narrative";

function show() {
  return renderAt("/", "/", <NarrativePanel planId={7} />);
}

describe("NarrativePanel", () => {
  beforeEach(() => api.reset());

  it("shows the wording, labelled as template wording", async () => {
    api.on("get", PATH, () => vanNarrative());
    show();
    expect(screen.getByTestId("narrative-panel")).toBeInTheDocument();
    const text = await screen.findByTestId("narrative");
    expect(text).toHaveTextContent("Van 1 serves two shops first");
    expect(text).toHaveAttribute("data-generated-by", "template");
    expect(text).toHaveTextContent("Template wording");
    expect(screen.queryAllByTestId("source-chip").map((c) => c.getAttribute("data-source"))).toEqual(["model"]);
    expect(api.get).toHaveBeenCalledWith(PATH, { params: { lang: "en" } });
  });

  it("marks LLM wording as AI-generated", async () => {
    api.on("get", PATH, () => vanNarrative({ generated_by: "llm" }));
    show();
    await screen.findByTestId("narrative");
    expect(screen.getAllByTestId("source-chip").map((c) => c.getAttribute("data-source"))).toEqual(["model", "ai"]);
  });

  it("shows a skeleton while loading", () => {
    api.on("get", PATH, () => new Promise(() => undefined));
    show();
    expect(within(screen.getByTestId("narrative-panel")).getByRole("status")).toHaveAttribute("aria-busy", "true");
  });

  it("shows an error with a retry that loads the text", async () => {
    let calls = 0;
    api.on("get", PATH, () => {
      calls += 1;
      if (calls === 1) throw new Error("network");
      return vanNarrative({ text: "Second try worked." });
    });
    show();
    expect(await screen.findByText("The explanation could not be loaded.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    await waitFor(() => expect(screen.getByTestId("narrative")).toHaveTextContent("Second try worked."));
  });
});
