import { expect, test, type Page } from "@playwright/test";

import { loginAs } from "./helpers";

// Live clock (CLOCK_MODE=live, the default): every page shows the real present in Dhaka.
// Labels follow the user's language (bn-first), so dates are matched in both en and bn.

const EN_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const BN_MONTHS = ["জানু", "ফেব্রু", "মার্চ", "এপ্রি", "মে", "জুন", "জুলা", "আগ", "সেপ্টে", "অক্টো", "নভে", "ডিসে"];
const BN_DIGITS = "০১২৩৪৫৬৭৮৯";

function dhakaToday(): { day: number; month: number } {
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Dhaka", day: "numeric", month: "numeric" }).formatToParts(new Date());
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value);
  return { day: get("day"), month: get("month") - 1 };
}

function bn(n: number): string {
  return String(n).replace(/\d/g, (d) => BN_DIGITS[Number(d)] ?? d);
}

/** "5 Oct" | "৫ অক্টো": the way TimeText writes a Dhaka date. */
function todayPattern(): RegExp {
  const { day, month } = dhakaToday();
  return new RegExp(`(${day} ${EN_MONTHS[month]}|${bn(day)} ${BN_MONTHS[month]})`);
}

/** The old frozen clock: 30 April 2026. Only checked when today is not in April. `scope` defaults
 *  to the page; /admin/data passes its summary panel (the embedded assumptions document describes
 *  the fixed timeline on purpose). */
async function expectNoFrozenDate(page: Page, scope = page.locator("main")): Promise<void> {
  if (dhakaToday().month === 3) return;
  await expect(scope).not.toContainText(/\b\d{1,2} Apr\b|এপ্রি/);
}

test.describe("live clock", () => {
  test.use({ viewport: { width: 1280, height: 900 }, reducedMotion: "reduce" });

  test("admin sees the live data clock at today's Dhaka date", async ({ page }) => {
    await loginAs(page, "admin");
    const card = page.getByTestId("data-clock-panel");
    await expect(card).toBeVisible({ timeout: 30_000 });
    await expect(card.getByTestId("clock-mode")).toHaveText(/Live|লাইভ/);
    await expect(card).toContainText(todayPattern());
    await expect(card.getByTestId("run-tick")).toBeVisible();
    await expectNoFrozenDate(page);

    await page.goto("/admin/data");
    const summary = page.getByTestId("data-summary");
    await expect(summary).toContainText(todayPattern(), { timeout: 30_000 });
    await expectNoFrozenDate(page, summary);
  });

  test("agent pages say 'live simulation' and show no frozen date", async ({ page }) => {
    await loginAs(page, "agent");
    const chip = page.getByTestId("freshness-chip");
    await expect(chip).toHaveAttribute("data-clock-mode", "live", { timeout: 30_000 });
    await expect(chip).toContainText(/Live simulation \(synthetic data\)|লাইভ সিমুলেশন/);
    await expectNoFrozenDate(page);
    for (const path of ["/agent/forecast", "/agent/stockout"]) {
      await page.goto(path);
      await expect(page.getByTestId("freshness-chip")).toHaveAttribute("data-clock-mode", "live", { timeout: 30_000 });
      await expectNoFrozenDate(page);
    }
  });

  test("the distributor sees the same live clock", async ({ page }) => {
    await loginAs(page, "distributor");
    await page.goto("/distributor/agents");
    await expect(page.getByTestId("freshness-chip")).toHaveAttribute("data-clock-mode", "live", { timeout: 30_000 });
    await expectNoFrozenDate(page);
  });
});
