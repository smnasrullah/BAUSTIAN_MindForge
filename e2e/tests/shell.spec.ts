import { expect, test } from "@playwright/test";

import { hasHorizontalScroll, loginAs, logoutFromMenu } from "./helpers";

test("logout from the avatar menu ends the session", async ({ page }) => {
  await loginAs(page, "distributor");
  await logoutFromMenu(page);
  await page.goto("/distributor");
  await expect(page).toHaveURL(/\/login$/);
});

test("Ctrl+K opens the command palette and jumps to an agent", async ({ page }) => {
  await loginAs(page, "distributor");
  await page.keyboard.press("Control+k");
  const palette = page.getByTestId("command-palette");
  await expect(palette).toBeVisible();

  await palette.getByRole("combobox").fill("AGT-0001");
  const hit = palette.getByRole("option", { name: /AGT-0001/ });
  await expect(hit).toBeVisible();
  await hit.click();
  await expect(page).toHaveURL(/\/distributor\/agents\/\d+$/);
  await expect(palette).toHaveCount(0);
});

// scripts/check -E2E first runs `python bootstrap.py e2e-fixtures` (includes seed-notifications):
// the distributor's inbox is all read except one unread notice, every run, no DB reset. Saved
// language/digits are not reset, so labels are matched in both (en | bn).
// Help requests made earlier in the suite (help-requests.spec) or by the background scheduler
// may add live notices for this distributor, so the count is read, not assumed to be one.
test("notifications can be read from the bell", async ({ page }) => {
  await loginAs(page, "distributor");
  const badge = page.getByTestId("notification-badge");
  await expect(badge).toHaveText(/^[0-9০-৯]+\+?$/);
  const shown = (await badge.textContent()) ?? "";
  const unread = Number(shown.replace(/[০-৯]/g, (d) => String("০১২৩৪৫৬৭৮৯".indexOf(d))).replace("+", ""));
  expect(unread).toBeGreaterThanOrEqual(1); // e2e-fixtures leaves at least one unread notice
  await page.getByTestId("notification-bell").click();
  const panel = page.getByRole("dialog", { name: /^(Notifications|নোটিফিকেশন)$/ });
  await expect(panel).toBeVisible();
  const unreadRows = panel.locator('[data-testid="notification-row"][data-unread="true"]');
  await expect.poll(async () => unreadRows.count()).toBeGreaterThanOrEqual(Math.min(unread, 1));
  if (!shown.endsWith("+")) expect(await unreadRows.count()).toBeLessThanOrEqual(unread);

  await panel.getByRole("button", { name: /^(Mark all read|সব পড়া হয়েছে)$/ }).click();
  await expect(badge).toHaveCount(0);
  await expect(unreadRows).toHaveCount(0);

  await panel.getByRole("link", { name: /^(View all notifications|সব নোটিফিকেশন দেখুন)$/ }).click();
  await expect(page).toHaveURL(/\/notifications$/);
  await page.goto("/notifications?status=unread");
  await expect(page.getByText(/^(All caught up|সব দেখা হয়ে গেছে)$/)).toBeVisible();
});

test("preferences persist on the server", async ({ page }) => {
  await loginAs(page, "admin");
  await page.goto("/settings");
  const bangla = page.getByRole("radio", { name: "১২৩" });
  const latin = page.getByRole("radio", { name: "123" });
  await bangla.click();
  await expect(bangla).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("theme-preview")).toContainText("৳১,২০,০০০");

  try {
    // Drop the local copy: after reload only the server profile can bring the choice back.
    await page.evaluate(() => window.localStorage.clear());
    await page.reload();
    await expect(page.getByRole("radio", { name: "১২৩" })).toHaveAttribute("aria-checked", "true");
  } finally {
    await page.getByRole("radio", { name: "123" }).click();
    await expect(latin).toHaveAttribute("aria-checked", "true");
  }
});

test("agent: sidebar shell at 1280px, bottom nav at 390px", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await loginAs(page, "agent");
  const sidebar = page.locator("aside");
  await expect(sidebar).toBeVisible();
  await expect(sidebar.locator('a[href="/agent/copilot"]')).toBeVisible();
  await expect(page.getByTestId("bottom-nav")).toHaveCount(0);
  expect(await hasHorizontalScroll(page)).toBe(false);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByTestId("bottom-nav")).toBeVisible();
  await expect(page.locator("aside")).toHaveCount(0);
  expect(await hasHorizontalScroll(page)).toBe(false);
});

test("the tour can be replayed from Help", async ({ page }) => {
  await loginAs(page, "admin");
  await page.goto("/help");
  await page.getByRole("button", { name: "Replay the tour" }).click();
  const tour = page.getByTestId("onboarding-tour");
  await expect(tour).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(tour).toHaveCount(0);
});
