import { beforeEach, describe, expect, it, vi } from "vitest";

import { vanNarrative, vanPage, vanPlan } from "../features/distributor/vanRoutes/testFixtures";
import { api as realApi } from "../lib/api";
import type { FakeApi } from "../test/fakeApi";
import { createVanPlan, decideVanPlan, getVanNarrative, getVanPlan, listVanPlans, vanPlanSchema } from "./vanPlans";

vi.mock("../lib/api", async () => {
  const { createFakeApi } = await import("../test/fakeApi");
  return { api: createFakeApi(), authClient: { post: vi.fn() }, refreshAccessToken: vi.fn() };
});

const api = realApi as unknown as FakeApi;
const BASE = "/distributor/van-plans";

describe("van plan API", () => {
  beforeEach(() => api.reset());

  it("posts the vehicle overrides and returns a parsed plan", async () => {
    api.on("post", BASE, () => vanPlan());
    const plan = await createVanPlan({ vehicles: { count: 3 } });
    expect(api.post).toHaveBeenCalledWith(BASE, { vehicles: { count: 3 } });
    expect(plan.depot.code).toBe("DST-DHK");
    expect(plan.routes).toHaveLength(2);
    expect(plan.advisory).toBe(true);
  });

  it("reads one plan, a page of plans, and the narrative in the asked language", async () => {
    api.on("get", `${BASE}/7`, () => vanPlan());
    api.on("get", BASE, () => vanPage([vanPlan()]));
    api.on("get", `${BASE}/7/narrative`, () => vanNarrative({ lang: "bn" }));
    expect((await getVanPlan(7)).id).toBe(7);
    expect((await listVanPlans({ status: "pending" })).items).toHaveLength(1);
    expect(api.get).toHaveBeenCalledWith(BASE, { params: { status: "pending" } });
    expect((await getVanNarrative(7, "bn")).lang).toBe("bn");
    expect(api.get).toHaveBeenCalledWith(`${BASE}/7/narrative`, { params: { lang: "bn" } });
  });

  it("sends a decision with its note", async () => {
    api.on("post", `${BASE}/7/decision`, () => vanPlan({ status: "rejected" }));
    const plan = await decideVanPlan(7, { decision: "reject", note: "Too far" });
    expect(api.post).toHaveBeenCalledWith(`${BASE}/7/decision`, { decision: "reject", note: "Too far" });
    expect(plan.status).toBe("rejected");
  });

  it("rejects a response that breaks the contract instead of showing NaN", async () => {
    api.on("get", `${BASE}/7`, () => ({ ...vanPlan(), km: "far" }));
    await expect(getVanPlan(7)).rejects.toThrow();
  });

  it("accepts the fixture and refuses an unknown status or a plan that is not advisory", () => {
    expect(vanPlanSchema.safeParse(vanPlan()).success).toBe(true);
    expect(vanPlanSchema.safeParse({ ...vanPlan(), status: "done" }).success).toBe(false);
    expect(vanPlanSchema.safeParse({ ...vanPlan(), advisory: false }).success).toBe(false);
  });
});
