import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.NEXOLAB_REPORTS_BASE_URL ?? "http://127.0.0.1:3104";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "rendered-reports.production.e2e.ts",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  timeout: 150_000,
  expect: { timeout: 25_000 },
  reporter: process.env.CI
    ? [["line"], ["html", { outputFolder: "playwright-report-rendered-reports", open: "never" }]]
    : "list",
  outputDir: "test-results-rendered-reports",
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
