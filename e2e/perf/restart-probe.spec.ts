// Diagnostic for a backend restart while a page is open (the host restarts the container):
//   PROBE_RESTART=1 npx playwright test -c playwright.perf.config.ts restart-probe
// Prints when the reconnect banner appears and disappears and whether the session survived.
import { expect, test } from "@playwright/test";

import { loginAs } from "../tests/helpers";

test("backend restart probe", async ({ page }) => {
  test.skip(!process.env.PROBE_RESTART, "diagnostic only: set PROBE_RESTART");
  test.setTimeout(240_000);
  await loginAs(page, "distributor");
  await page.goto("/distributor/swaps");
  await expect(page.getByTestId("app-shell")).toBeVisible();
  console.log("READY_FOR_RESTART");
  const t0 = Date.now();
  const banner = page.getByTestId("server-banner");
  // The page keeps polling (notifications, help badge); a failed poll shows the banner.
  await expect(banner).not.toBeEmpty({ timeout: 120_000 });
  console.log(`BANNER_SHOWN after ${Date.now() - t0} ms: ${(await banner.innerText()).trim()}`);
  await expect(page.getByTestId("server-banner").getByText(/Reconnect|আবার যুক্ত/)).toBeVisible({ timeout: 120_000 });
  console.log(`RECONNECTED after ${Date.now() - t0} ms`);
  await expect(page).toHaveURL(/\/distributor\/swaps$/);
  await expect(page.getByTestId("app-shell")).toBeVisible();
  console.log("SESSION_KEPT");
});
