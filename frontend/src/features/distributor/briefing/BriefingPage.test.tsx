import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api as realApi } from "../../../lib/api";
import type { FakeApi } from "../../../test/fakeApi";
import { signIn } from "../../auth/testUtils";
import { llmText } from "../testFixtures";
import { renderAt } from "../testRender";
import { BriefingPage } from "./BriefingPage";

vi.mock("../../../lib/api", async () => {
  const { createFakeApi } = await import("../../../test/fakeApi");
  return { api: createFakeApi(), authClient: { post: vi.fn() }, refreshAccessToken: vi.fn() };
});

const api = realApi as unknown as FakeApi;

describe("daily briefing", () => {
  beforeEach(() => {
    api.reset();
    signIn("distributor");
  });

  it("shows the AI wording labelled as AI-generated", async () => {
    api.on("get", "/distributor/briefing", () => llmText());
    renderAt("/distributor/briefing", "/distributor/briefing", <BriefingPage />);
    expect(await screen.findByText("Three agents may run short of cash today; Karim Telecom first.")).toBeInTheDocument();
    expect(screen.getByTestId("wording-chip")).toHaveAttribute("data-generated-by", "llm");
    expect(api.get).toHaveBeenCalledWith("/distributor/briefing", { params: { lang: "en" } });
  });

  it("falls back to the template text and says so", async () => {
    api.on("get", "/distributor/briefing", () => llmText({ generated_by: "template", fallback_reason: "not_configured", text: "Template: 3 agents need cash today." }));
    renderAt("/distributor/briefing", "/distributor/briefing", <BriefingPage />);
    expect(await screen.findByText("Template: 3 agents need cash today.")).toBeInTheDocument();
    expect(screen.getByTestId("wording-chip")).toHaveAttribute("data-generated-by", "template");
    expect(screen.getByTestId("briefing-fallback")).toBeInTheDocument();
  });

  it("labels template wording served because no API key is set", async () => {
    api.on("get", "/distributor/briefing", () => llmText({ generated_by: "template", no_api_key: true, text: "Template: 3 agents need cash today." }));
    renderAt("/distributor/briefing", "/distributor/briefing", <BriefingPage />);
    const chip = await screen.findByTestId("wording-chip");
    expect(chip).toHaveTextContent("Template wording (no API key)");
    expect(chip).toHaveAttribute("data-generated-by", "template");
  });

  it("keeps the plain template label when a key exists but the call failed", async () => {
    api.on("get", "/distributor/briefing", () => llmText({ generated_by: "template", fallback_reason: "error", text: "Template: 3 agents need cash today." }));
    renderAt("/distributor/briefing", "/distributor/briefing", <BriefingPage />);
    expect(await screen.findByTestId("wording-chip")).toHaveTextContent(/^Template wording$/);
  });
});
