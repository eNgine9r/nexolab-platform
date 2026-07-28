import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.NEXOLAB_DR_BROWSER_BASE_URL ?? "http://127.0.0.1:3114";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "disaster-recovery.production.e2e.ts",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  reporter: process.env.CI
    ? [["line"], ["html", { outputFolder: "playwright-report-disaster-recovery", open: "never" }]]
    : "list",
  outputDir: "test-results-disaster-recovery-browser/playwright",
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
