import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.NEXOLAB_BROKER_CONTROL_FRONTEND_URL ?? "http://127.0.0.1:3110";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "broker-control.production.e2e.ts",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 30_000 },
  reporter: process.env.CI
    ? [["line"], ["html", { outputFolder: "playwright-report-broker-control", open: "never" }]]
    : "list",
  outputDir: "test-results-broker-control/browser",
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
