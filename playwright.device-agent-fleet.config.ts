import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.NEXOLAB_DEVICE_AGENT_FLEET_FRONTEND_URL ?? "http://127.0.0.1:3112";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "device-agent-fleet.production.e2e.ts",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 30_000 },
  reporter: process.env.CI
    ? [["line"], ["html", { outputFolder: "playwright-report-device-agent-fleet", open: "never" }]]
    : "list",
  outputDir: "test-results-device-agent-fleet/browser",
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
