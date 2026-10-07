// Every route for every role at 1440 and 390 px: no console errors, no failed requests, no
// sideways scroll, no skeleton left behind, real content. Then each signed-in role tries the
// other roles' areas and must land on 403 without seeing their data.
import { expect, test, type Page } from "@playwright/test";

import { ROUTES, type Role } from "../routes";
import { hasHorizontalScroll, loginAs, pathOf, watchPage } from "./helpers";

const VIEWPORTS = [
  { name: "1440", width: 1440, height: 900 },
  { name: "390", width: 390, height: 844 },
] as const;
const ROLES: (Role | "public")[] = ["public", "agent", "distributor", "admin"];
const HOME: Record<Role, string> = { agent: "/agent", distributor: "/distributor", admin: "/admin" };

/** All skeletons gone (data blocks show content, empty or error state). */
async function noSkeletonLeft(page: Page): Promise<void> {
  await expect
    .poll(() => page.locator('[aria-busy="true"]').count(), { timeout: 20_000, message: "a skeleton never resolved" })
    .toBe(0);
}

for (const vp of VIEWPORTS) {
  for (const role of ROLES) {
    const routes = ROUTES.filter((r) => r.as === role).map((r) => r.path);
    if (routes.length === 0) continue;
    test(`sweep ${role} at ${vp.name}px (${routes.length} routes)`, async ({ page }) => {
      test.setTimeout(60_000 + routes.length * 20_000);
      await page.setViewportSize({ width: vp.width, height: vp.height });
      if (role !== "public") await loginAs(page, role);
      const { problems } = watchPage(page);
      for (const path of routes) {
        await page.goto(path);
        await page.waitForLoadState("networkidle");
        expect(pathOf(page), `${path} redirected away`).toBe(path);
        // The design kit (dev-only, not in production builds) shows loading states and
        // oversized demo visuals on purpose.
        const kit = path === "/dev/kit";
        if (!kit) await noSkeletonLeft(page);
        const main = page.locator("main");
        await expect(main, `${path}: one <main>`).toHaveCount(1);
        expect((await main.innerText()).trim().length, `${path}: <main> has no text`).toBeGreaterThan(0);
        if (!kit) expect(await hasHorizontalScroll(page), `${path}: sideways scroll at ${vp.name}px`).toBe(false);
      }
      expect(problems, problems.join("\n")).toEqual([]);
    });
  }
}

const SIGNED_IN: Role[] = ["agent", "distributor", "admin"];
for (const role of SIGNED_IN) {
  test(`${role} cannot open the other roles' pages`, async ({ page }) => {
    await loginAs(page, role);
    const foreign = ROUTES.filter((r) => r.as !== "public" && r.as !== role && r.path.startsWith(HOME[r.as as Role]));
    const paths = [...new Set(foreign.map((r) => r.path))];
    expect(paths.length).toBeGreaterThan(0);
    for (const path of paths) {
      await page.goto(path);
      await expect(page, `${role} reached ${path}`).toHaveURL(/\/403$/);
    }
  });
}
