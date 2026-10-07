// Web vitals per key route and role under throttling (4x CPU, DevTools "Slow 4G").
// Run: docker compose -p agentpulse-verify --profile e2e run --rm --no-deps -T e2e \
//        npx playwright test -c playwright.perf.config.ts
// Writes perf/out/vitals-<PERF_LABEL>.json; with PERF_ENFORCE=1 every budget is asserted.
import { appendFileSync, mkdirSync } from "node:fs";

import { expect, test, type BrowserContext, type Page } from "@playwright/test";

import type { Role } from "../routes";
import { ACCOUNTS, dismissTour, fillLogin } from "../tests/helpers";

const SLOW_4G = { offline: false, latency: 562.5, downloadThroughput: 180_000, uploadThroughput: 84_375 };
const BUDGET = { lcpMs: 2500, cls: 0.1, inpMs: 200, routeMs: 200, longTaskMs: 200 };
const VIEWPORTS = [
  { name: "1440", width: 1440, height: 900 },
  { name: "390", width: 390, height: 844 },
] as const;

const KEY_ROUTES: Record<Role | "public", string[]> = {
  public: ["/", "/login"],
  agent: ["/agent", "/agent/forecast", "/agent/what-if", "/agent/copilot"],
  distributor: ["/distributor", "/distributor/agents", "/distributor/swaps", "/distributor/impact"],
  admin: ["/admin", "/admin/users", "/admin/audit"],
};
// Route-change probe: from the role's home, click a nav link to a page whose data is cached.
const ROUTE_CHANGE: Record<Role, string> = {
  agent: "/agent/forecast",
  distributor: "/distributor/agents",
  admin: "/admin/users",
};

interface Row {
  role: string;
  route: string;
  viewport: string;
  cache: "cold" | "warm";
  lcpMs: number | null;
  cls: number;
  inpMs: number | null;
  maxLongTaskMs: number;
  heapMb: number | null;
  readyMs: number;
}
const rows: Row[] = [];
const OUT = `perf/out/vitals-${process.env.PERF_LABEL ?? "latest"}.jsonl`;

/** One JSON line per measurement, appended as measured (survives a failing test). */
function record(entry: object): void {
  mkdirSync("perf/out", { recursive: true });
  appendFileSync(OUT, `${JSON.stringify(entry)}
`);
}
const routeChanges: { role: string; viewport: string; ms: number }[] = [];

const OBSERVE = () => {
  const v = { lcp: 0, cls: 0, inp: 0, longTask: 0 };
  (window as unknown as { __vitals: typeof v }).__vitals = v;
  const po = (type: string, cb: (e: PerformanceEntry) => void, extra: object = {}) => {
    try {
      new PerformanceObserver((l) => l.getEntries().forEach(cb)).observe({ type, buffered: true, ...extra });
    } catch {
      /* entry type not supported */
    }
  };
  po("largest-contentful-paint", (e) => (v.lcp = e.startTime));
  po("layout-shift", (e) => {
    const s = e as PerformanceEntry & { value: number; hadRecentInput: boolean };
    if (!s.hadRecentInput) v.cls += s.value;
  });
  po("longtask", (e) => (v.longTask = Math.max(v.longTask, e.duration)));
  po(
    "event",
    (e) => {
      const ev = e as PerformanceEntry & { interactionId?: number };
      if (ev.interactionId) v.inp = Math.max(v.inp, e.duration);
    },
    { durationThreshold: 16 },
  );
};

type Cdp = Awaited<ReturnType<BrowserContext["newCDPSession"]>>;

async function throttle(cdp: Cdp, on: boolean): Promise<void> {
  await cdp.send("Network.emulateNetworkConditions", on ? SLOW_4G : { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: on ? 4 : 1 });
}

/** The real page is on screen and its data loaded: its marker exists and no skeleton
 * (aria-busy) is left. A marker, not any h1: the startup "Preparing" screen has an h1 too. */
async function settled(page: Page): Promise<void> {
  await page.waitForFunction(
    () => {
      const marker =
        location.pathname === "/" ? "#hero-title" : location.pathname === "/login" ? "#email" : '[data-testid="app-shell"] h1';
      return document.querySelector(marker) !== null && document.querySelectorAll('[aria-busy="true"]').length === 0;
    },
    undefined,
    { timeout: 60_000, polling: 100 },
  );
}

/** INP probe: a pointer click on empty margin and a key press, plus the avatar menu if shown. */
async function interact(page: Page): Promise<void> {
  const size = page.viewportSize() ?? { width: 390, height: 844 };
  await page.mouse.click(4, Math.round(size.height / 2));
  await page.keyboard.press("Tab");
  const menu = page.getByTestId("avatar-menu");
  if (await menu.isVisible()) {
    await menu.click({ timeout: 5_000 }).catch(() => undefined);
    await page.keyboard.press("Escape");
  }
  await page.waitForTimeout(300);
}

async function measure(page: Page, role: string, route: string, viewport: string, cache: Row["cache"]) {
  const t0 = Date.now();
  await page.goto(route);
  await settled(page);
  const readyMs = Date.now() - t0;
  await page.waitForTimeout(1000); // let late shifts and the LCP candidate settle
  await interact(page);
  const v = await page.evaluate(() => {
    const w = window as unknown as { __vitals: { lcp: number; cls: number; inp: number; longTask: number } };
    const mem = (performance as unknown as { memory?: { usedJSHeapSize: number } }).memory;
    return { ...w.__vitals, heap: mem ? mem.usedJSHeapSize / 1048576 : null };
  });
  const r: Row = {
    role, route, viewport, cache, readyMs,
    lcpMs: v.lcp ? Math.round(v.lcp) : null,
    cls: Math.round(v.cls * 1000) / 1000,
    inpMs: v.inp ? Math.round(v.inp) : null,
    maxLongTaskMs: Math.round(v.longTask),
    heapMb: v.heap === null ? null : Math.round(v.heap * 10) / 10,
  };
  rows.push(r);
  record({ kind: "page", ...r });
  // Logged as measured, so a later failure in the same test keeps the numbers.
  console.log(
    `${r.role.padEnd(11)} ${r.route.padEnd(22)} ${r.viewport} ${r.cache} ready=${r.readyMs} ` +
      `lcp=${r.lcpMs} cls=${r.cls} inp=${r.inpMs} longtask=${r.maxLongTaskMs} heap=${r.heapMb}`,
  );
}

for (const role of Object.keys(KEY_ROUTES) as (Role | "public")[]) {
  test(`vitals ${role}`, async ({ browser }) => {
    for (const vp of VIEWPORTS) {
      // One signed-in context per viewport: the refresh cookie rotates on every page load, so
      // it must stay in the context that holds it. "Cold" clears the HTTP cache, not cookies.
      const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
      await ctx.addInitScript(OBSERVE);
      const page = await ctx.newPage();
      const cdp = await ctx.newCDPSession(page);
      await cdp.send("Network.enable");
      if (role !== "public") {
        await fillLogin(page, ACCOUNTS[role].email, ACCOUNTS[role].password);
        await expect(page).toHaveURL((u) => u.pathname === ACCOUNTS[role].home);
        await dismissTour(page);
      }
      for (const route of KEY_ROUTES[role]) {
        await throttle(cdp, false);
        await cdp.send("Network.clearBrowserCache");
        await throttle(cdp, true);
        await measure(page, role, route, vp.name, "cold");
        await measure(page, role, route, vp.name, "warm");
      }
      if (role !== "public") {
        const home = ACCOUNTS[role].home;
        const target = ROUTE_CHANGE[role];
        // In-app navigation only (a reload would empty the query cache): home -> target loads
        // the target's data, back home, then the measured click to the now-cached target.
        await throttle(cdp, false);
        await page.goto(home);
        await settled(page);
        const navTo = async (path: string) => {
          const link = page.locator(`a[href="${path}"]`).locator("visible=true").first();
          const shown = await link.waitFor({ timeout: 5_000 }).then(() => true, () => false);
          if (!shown) await page.getByTestId("sidebar-open").click(); // mobile: the nav is a drawer
          return link;
        };
        await (await navTo(target)).click();
        await page.waitForFunction((p) => location.pathname === p, target);
        await settled(page);
        await (await navTo(home)).click();
        await page.waitForFunction((p) => location.pathname === p, home);
        await settled(page);
        await throttle(cdp, true);
        const link = await navTo(target);
        const start = await page.evaluate(() => performance.now());
        await link.click();
        await page.waitForFunction((p) => location.pathname === p, target);
        await settled(page);
        const end = await page.evaluate(() => performance.now());
        const change = { role, viewport: vp.name, ms: Math.round(end - start) };
        routeChanges.push(change);
        record({ kind: "route-change", ...change });
        console.log(`route-change ${role} ${vp.name} ${change.ms}ms`);
      }
      await ctx.close();
    }
  });
}

test.afterAll(() => {
  if (process.env.PERF_ENFORCE === "1") {
    const over = rows.filter(
      (r) =>
        (r.lcpMs ?? 0) > BUDGET.lcpMs ||
        r.cls > BUDGET.cls ||
        (r.inpMs ?? 0) > BUDGET.inpMs ||
        r.maxLongTaskMs > BUDGET.longTaskMs,
    );
    expect(over, JSON.stringify(over)).toEqual([]);
    expect(routeChanges.filter((c) => c.ms > BUDGET.routeMs)).toEqual([]);
  }
});
