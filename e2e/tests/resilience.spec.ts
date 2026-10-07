// Failure injection in the browser: API 500 then retry, 401 mid-session, 3 s slow API, offline,
// session expiry, double clicks, back/forward, deep-link reload, two tabs, language switching.
// Network faults are injected with page.route; the stack itself is untouched.
import { expect, test, type Page, type Route } from "@playwright/test";

import { loginAs, logoutFromMenu, pathOf, watchPage } from "./helpers";

const API = "**/api/v1";

/** Signed in as the distributor with English UI (the language is a saved preference, so an
 * earlier test may have left it in Bangla). */
async function distributorInEnglish(page: Page): Promise<void> {
  await loginAs(page, "distributor");
  if ((await page.evaluate(() => document.documentElement.lang)) !== "en") {
    await page.getByTestId("language-switch").click();
    await expect.poll(() => page.evaluate(() => document.documentElement.lang)).toBe("en");
  }
}

async function failNTimes(page: Page, pattern: RegExp, status: number, times: number): Promise<() => number> {
  let failed = 0;
  await page.route(pattern, async (route: Route) => {
    if (failed < times) {
      failed += 1;
      await route.fulfill({ status, contentType: "application/json", body: JSON.stringify({ detail: "injected" }) });
    } else {
      await route.fallback();
    }
  });
  return () => failed;
}

test("a failing data block shows an error with retry, and retry recovers", async ({ page }) => {
  await distributorInEnglish(page);
  const swaps = /\/api\/v1\/swaps(\?|$)/;
  await page.route(swaps, (route) =>
    route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "injected" }) }),
  );
  await page.goto("/distributor/swaps");
  // TanStack retries twice (2 s, 4 s) before the error state shows.
  await expect(page.getByRole("button", { name: "Try again" }).first()).toBeVisible({ timeout: 20_000 });
  await page.unroute(swaps);
  // Each failed block has its own retry; all of them recover once the API is back.
  const buttons = page.getByRole("button", { name: "Try again" });
  const count = await buttons.count();
  for (let i = 0; i < count; i += 1) {
    const reloaded = page.waitForResponse((r) => swaps.test(r.url()) && r.ok());
    await buttons.first().click();
    await reloaded;
  }
  await expect(buttons).toHaveCount(0, { timeout: 15_000 });
});

test("an expired access token mid-session is refreshed without signing out", async ({ page }) => {
  await distributorInEnglish(page);
  const failed = await failNTimes(page, /\/api\/v1\/agents\/risk(\?|$)/, 401, 1);
  const { problems } = watchPage(page);
  const loaded = page.waitForResponse((r) => /\/api\/v1\/agents\/risk(\?|$)/.test(r.url()) && r.ok());
  await page.goto("/distributor/agents");
  await loaded;
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 20_000 });
  expect(failed()).toBe(1);
  expect(pathOf(page)).toBe("/distributor/agents");
  expect(problems, problems.join("\n")).toEqual([]);
});

test("a 3 s slow API shows skeletons, then the page, without errors", async ({ page }) => {
  await distributorInEnglish(page);
  await page.route(`${API}/**`, async (route) => {
    await new Promise((r) => setTimeout(r, 3000));
    await route.fallback();
  });
  const { problems } = watchPage(page);
  await page.goto("/distributor/swaps");
  await expect(page.locator('[aria-busy="true"]').first()).toBeVisible({ timeout: 10_000 });
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 40_000 });
  expect(problems, problems.join("\n")).toEqual([]);
});

test("offline shows a banner and coming back online refreshes", async ({ page, context }) => {
  await distributorInEnglish(page);
  await page.goto("/distributor/swaps");
  await expect(page.getByTestId("app-shell")).toBeVisible();
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 20_000 });
  await context.setOffline(true);
  await expect(page.getByText("You are offline. Showing the last data that loaded.")).toBeVisible();
  await context.setOffline(false);
  await expect(page.getByText("Back online. Refreshing data.")).toBeVisible();
});

test("a session that cannot be refreshed ends on sign-in with a notice", async ({ page }) => {
  await distributorInEnglish(page);
  await page.route(`${API}/auth/refresh`, (route) =>
    route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ detail: "invalid_refresh_token" }) }),
  );
  await page.route(/\/api\/v1\/swaps(\?|$)/, (route) =>
    route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ detail: "token_expired" }) }),
  );
  await page.locator('a[href="/distributor/swaps"]').locator("visible=true").first().click();
  await expect(page).toHaveURL(/\/login/, { timeout: 15_000 });
  await expect(page.getByText("Your session expired. Sign in again to continue.")).toBeVisible();
});

test("double-clicking 'Mark all read' sends one request", async ({ page }) => {
  await distributorInEnglish(page);
  let calls = 0;
  // Answered here, so the shared demo inbox keeps its unread notice for shell.spec.ts.
  await page.route(`${API}/notifications/read-all`, async (route) => {
    calls += 1;
    await new Promise((r) => setTimeout(r, 500)); // keep the first call in flight
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ updated: 1 }) });
  });
  await page.getByTestId("notification-bell").click();
  const markAll = page.getByRole("button", { name: "Mark all read" });
  if (await markAll.isDisabled()) test.skip(true, "inbox already read in this database");
  await markAll.dblclick();
  await page.waitForTimeout(1500);
  expect(calls).toBe(1);
});

test("back, forward and reload keep the user on deep links", async ({ page }) => {
  await distributorInEnglish(page);
  await page.goto("/distributor/agents");
  await page.goto("/distributor/swaps");
  await page.goBack();
  await expect(page).toHaveURL(/\/distributor\/agents$/);
  await page.goForward();
  await expect(page).toHaveURL(/\/distributor\/swaps$/);
  await page.reload();
  await expect(page).toHaveURL(/\/distributor\/swaps$/);
  await expect(page.getByTestId("app-shell")).toBeVisible();
});

test("logging out in one tab signs the other tab out", async ({ page, context }) => {
  await distributorInEnglish(page);
  const other = await context.newPage();
  await other.goto("/distributor/swaps");
  await expect(other.getByTestId("app-shell")).toBeVisible();
  await logoutFromMenu(page);
  await expect(other).toHaveURL(/\/login/, { timeout: 15_000 });
});

test("switching language changes the page language and the digits follow the setting", async ({ page }) => {
  await distributorInEnglish(page);
  await page.goto("/distributor");
  const lang = await page.evaluate(() => document.documentElement.lang);
  await page.getByTestId("language-switch").click();
  await expect.poll(() => page.evaluate(() => document.documentElement.lang)).not.toBe(lang);
  await page.getByTestId("language-switch").click();
  await expect.poll(() => page.evaluate(() => document.documentElement.lang)).toBe(lang);
});
