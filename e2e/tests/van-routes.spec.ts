import { expect, test } from "@playwright/test";

import { loginAs, logoutFromMenu, watchPage } from "./helpers";

interface PlanPayload {
  id: number;
  status: string;
  routes: { stops: { id: number }[] }[];
  unrouted: { id: number }[];
}

const PLANS = "/api/v1/distributor/van-plans";

test("van routes: create a plan, see its stops, approve it with a note, and the admin sees the audit entry", async ({ page }) => {
  const watch = watchPage(page);
  await loginAs(page, "distributor");
  await page.goto("/distributor/van-routes");
  await expect(page.getByTestId("van-routes-page")).toBeVisible();

  // Create (or re-plan): the header button when a plan is open, the empty-state button when none is.
  const created = page.waitForResponse((res) => new URL(res.url()).pathname === PLANS && res.request().method() === "POST");
  await page.getByTestId("van-empty").getByRole("button").or(page.getByTestId("van-replan")).first().click();
  const response = await created;
  expect(response.status(), "plan creation (a 503 means the forecasts are not ready)").toBe(201);
  const plan = (await response.json()) as PlanPayload;
  expect(plan.status).toBe("pending");
  await expect(page.getByTestId("van-routes-page")).toHaveAttribute("data-plan-id", String(plan.id));

  // Every stop of the plan is listed, served or skipped; skipped ones carry a reason.
  const stops = plan.routes.flatMap((r) => r.stops).length + plan.unrouted.length;
  await expect(page.getByTestId("van-stop")).toHaveCount(stops);
  await expect(page.getByTestId("plan-status-bar")).toHaveAttribute("data-status", "pending");
  await expect(page.getByTestId("drop-reason")).toHaveCount(plan.unrouted.length);
  if (stops > 0) {
    await expect(page.getByTestId("route-map-pane")).toBeVisible();
    await expect(page.getByTestId("savings-panel")).toBeVisible();
    await expect(page.getByTestId("fairness-panel")).toBeVisible();
    await expect(page.getByTestId("narrative")).toBeVisible();
  }

  // Approve: the note is mandatory, so the button stays off until one is written.
  await page.getByTestId("van-decide").click();
  const dialog = page.getByTestId("van-approve-dialog");
  await expect(dialog.getByTestId("van-approve")).toBeDisabled();
  const note = `E2E van plan check ${Date.now()}`;
  await dialog.getByTestId("van-note").fill(note);
  const decided = page.waitForResponse((res) => res.url().endsWith(`${PLANS}/${plan.id}/decision`) && res.request().method() === "POST");
  await dialog.getByTestId("van-approve").click();
  expect((await decided).ok()).toBe(true);
  await expect(page.getByTestId("plan-status-bar")).toHaveAttribute("data-status", "approved");
  await expect(page.getByTestId("plan-decision")).toContainText(note);
  await expect(page.getByTestId("van-decide")).toHaveCount(0);

  // The admin finds the decision, with the note, in the audit log.
  await logoutFromMenu(page);
  await loginAs(page, "admin");
  await page.goto("/admin/audit-log?action=van_plan.approve");
  await expect(page.getByTestId("admin-audit")).toBeVisible();
  // The action name also appears as a filter option, so look inside the row that carries our note.
  const row = page.getByRole("row").filter({ hasText: note });
  await expect(row).toHaveCount(1);
  await expect(row.getByText("van_plan.approve", { exact: true })).toBeVisible();
  await expect(row.getByText("van_plan #" + plan.id)).toBeVisible();

  expect(watch.problems).toEqual([]);
});

test("van routes is distributor-only: an agent is sent to the 403 page", async ({ page }) => {
  await loginAs(page, "agent");
  await page.goto("/distributor/van-routes");
  await expect(page).toHaveURL(/\/403$/);
});
