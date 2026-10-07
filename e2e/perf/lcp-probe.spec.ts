// Diagnostic: LCP element and the request waterfall for one cold load under the vitals throttling.
//   PROBE_ROUTE=/agent PROBE_ROLE=agent npx playwright test -c playwright.perf.config.ts lcp-probe
import { expect, test } from "@playwright/test";

import type { Role } from "../routes";
import { ACCOUNTS, dismissTour, fillLogin } from "../tests/helpers";

const route = process.env.PROBE_ROUTE ?? "/";
const role = process.env.PROBE_ROLE as Role | undefined;

test(`lcp probe ${route}`, async ({ browser }) => {
  const width = Number(process.env.PROBE_WIDTH ?? 1440);
  const page = await browser.newPage({ viewport: { width, height: width < 600 ? 844 : 900 }, reducedMotion: process.env.PROBE_REDUCED ? "reduce" : "no-preference" });
  test.skip(!process.env.PROBE_ROUTE, "diagnostic only: set PROBE_ROUTE");
  if (role) {
    await fillLogin(page, ACCOUNTS[role].email, ACCOUNTS[role].password);
    await expect(page).toHaveURL((u) => u.pathname === ACCOUNTS[role].home);
    await dismissTour(page);
  }
  await page.addInitScript(() => {
    const out: string[] = [];
    (window as unknown as { __lcp: string[] }).__lcp = out;
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) {
        const x = e as PerformanceEntry & { element?: Element; size: number; url: string };
        const el = x.element;
        const id = el ? `${el.tagName.toLowerCase()} "${(el.textContent ?? "").slice(0, 40)}"` : "(removed)";
        out.push(`LCP ${Math.round(e.startTime)}ms size=${x.size} ${x.url || id}`);
      }
    }).observe({ type: "largest-contentful-paint", buffered: true });
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) {
        const x = e as PerformanceEntry & { value: number; hadRecentInput: boolean; sources?: { node?: Node; previousRect: DOMRectReadOnly; currentRect: DOMRectReadOnly }[] };
        if (x.hadRecentInput || x.value < 0.005) continue;
        const what = (x.sources ?? []).map((s) => {
          const el = s.node instanceof Element ? s.node : s.node?.parentElement;
          const name = el ? `${el.tagName.toLowerCase()}.${String(el.className).split(" ").slice(0, 3).join(".")}` : "?";
          return `${name} y ${Math.round(s.previousRect.y)}->${Math.round(s.currentRect.y)} h ${Math.round(s.previousRect.height)}->${Math.round(s.currentRect.height)}`;
        });
        out.push(`CLS ${Math.round(e.startTime)}ms +${x.value.toFixed(3)} ${what.join(" | ")}`);
      }
    }).observe({ type: "layout-shift", buffered: true });
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) {
        const x = e as PerformanceEventTiming & { interactionId?: number };
        if (!x.interactionId) continue;
        const tgt = x.target instanceof Element ? x.target.tagName.toLowerCase() : "?";
        out.push(`EVT ${x.name} ${tgt} dur=${Math.round(x.duration)} delay=${Math.round(x.processingStart - x.startTime)} proc=${Math.round(x.processingEnd - x.processingStart)} present=${Math.round(x.startTime + x.duration - x.processingEnd)}`);
      }
    }).observe({ type: "event", buffered: true, durationThreshold: 16 } as PerformanceObserverInit);
    new MutationObserver(() =>
      out.push(`LANG ${Math.round(performance.now())}ms ${document.documentElement.lang} digits=${document.documentElement.dataset.digits ?? "-"}`),
    ).observe(document.documentElement, { attributes: true, attributeFilter: ["lang"] });
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) out.push(`LONGTASK ${Math.round(e.startTime)}ms ${Math.round(e.duration)}ms`);
    }).observe({ type: "longtask", buffered: true });
  });
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.clearBrowserCache");
  await cdp.send("Network.emulateNetworkConditions", { offline: false, latency: 562.5, downloadThroughput: 180_000, uploadThroughput: 84_375 });
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  await page.goto(route);
  await page.waitForTimeout(15_000);
  if (process.env.PROBE_WARM) {
    await page.goto(route);
    await page.waitForTimeout(8_000);
  }
  if (process.env.PROBE_INTERACT) {
    // The vitals spec's INP probe, step by step, with a marker per step in the output.
    const mark = (label: string) => page.evaluate((l) => (window as unknown as { __lcp: string[] }).__lcp.push(`STEP ${Math.round(performance.now())}ms ${l}`), label);
    await mark("click margin");
    await page.mouse.click(4, 422);
    await page.waitForTimeout(1500);
    await mark("tab");
    await page.keyboard.press("Tab");
    await page.waitForTimeout(1500);
    await mark("avatar");
    await page.getByTestId("avatar-menu").click({ timeout: 5_000 }).catch(() => undefined);
    await page.waitForTimeout(1500);
    await mark("escape");
    await page.keyboard.press("Escape");
    await page.waitForTimeout(1500);
  }
  const waterfall = await page.evaluate(() =>
    performance
      .getEntriesByType("resource")
      .map((e) => {
        const r = e as PerformanceResourceTiming;
        return `${String(Math.round(r.startTime)).padStart(6)}-${String(Math.round(r.responseEnd)).padStart(6)}ms ${String(r.transferSize).padStart(7)}B ${r.name.replace(location.origin, "").slice(0, 70)}`;
      }),
  );
  const lcp = await page.evaluate(() => (window as unknown as { __lcp: string[] }).__lcp);
  console.log([...waterfall, ...lcp].join("\n"));
});
