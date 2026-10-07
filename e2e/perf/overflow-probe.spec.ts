// Diagnostic: which elements stick out past the right edge (sideways scroll) on one route.
//   PROBE_ROUTE=/settings PROBE_ROLE=distributor PROBE_WIDTH=390 npx playwright test -c playwright.perf.config.ts overflow-probe
import { test } from "@playwright/test";

import type { Role } from "../routes";
import { loginAs } from "../tests/helpers";

test("overflow probe", async ({ page }) => {
  test.skip(!process.env.PROBE_ROUTE, "diagnostic only: set PROBE_ROUTE");
  await page.setViewportSize({ width: Number(process.env.PROBE_WIDTH ?? 390), height: 844 });
  const role = process.env.PROBE_ROLE as Role | undefined;
  if (role) await loginAs(page, role);
  await page.goto(process.env.PROBE_ROUTE ?? "/");
  await page.waitForLoadState("networkidle");
  const wide = await page.evaluate(([slack, all]) => {
    const out: string[] = [`scrollWidth=${document.documentElement.scrollWidth} innerWidth=${innerWidth}`];
    for (const el of Array.from(document.querySelectorAll<HTMLElement>("body *"))) {
      const r = el.getBoundingClientRect();
      if (r.right > innerWidth + slack && r.width > 0) {
        const kids = Array.from(el.children).some((c) => c.getBoundingClientRect().right > innerWidth);
        if (!kids || all) out.push(`${el.tagName.toLowerCase()}.${String(el.className).slice(0, 90)} right=${r.right.toFixed(2)} w=${Math.round(r.width)} "${(el.textContent ?? "").trim().slice(0, 40)}"`);
      }
    }
    return out;
  }, [Number(process.env.PROBE_SLACK ?? 1), Boolean(process.env.PROBE_ALL)] as const);
  console.log(wide.slice(0, 15).join("\n"));
});
