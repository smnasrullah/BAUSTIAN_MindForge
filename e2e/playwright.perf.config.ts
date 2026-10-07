import { defineConfig, devices } from "@playwright/test";

// Web-vitals budget run (scripts/check -Perf), separate from the functional suite.
const baseURL = process.env.E2E_BASE_URL ?? "http://frontend";

export default defineConfig({
  testDir: "./perf",
  globalSetup: "./global-setup.ts",
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 1_200_000,
  expect: { timeout: 20_000 },
  reporter: [["list"]],
  outputDir: "perf/out/results",
  use: { baseURL, screenshot: "only-on-failure", video: "off", trace: "off", navigationTimeout: 90_000, actionTimeout: 30_000 },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
