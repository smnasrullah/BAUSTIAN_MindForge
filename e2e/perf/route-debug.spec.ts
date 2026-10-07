import { test } from "@playwright/test";

import { loginAs } from "../tests/helpers";

test("route debug", async ({ page }) => {
  test.skip(!process.env.PROBE_ROUTE, "diagnostic only");
  await loginAs(page, "distributor");
  const seen: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/api/v1/")) seen.push(`req ${r.url().replace(/^https?:\/\/[^/]+/, "")}`); });
  await page.route(/\/api\/v1\/agents\/risk(\?|$)/, async (route) => { seen.push(`ROUTED ${route.request().url()}`); await route.fallback(); });
  await page.goto(process.env.PROBE_ROUTE ?? "/distributor/agents");
  await page.waitForTimeout(4000);
  console.log(seen.join("\n"));
});
