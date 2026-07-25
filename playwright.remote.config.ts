import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

const dashboardUrl = process.env.NEXOLAB_REMOTE_DASHBOARD_URL;
if (!dashboardUrl) {
  throw new Error("NEXOLAB_REMOTE_DASHBOARD_URL is required for remote acceptance.");
}

const evidenceDirectory = process.env.NEXOLAB_REMOTE_EVIDENCE_DIR ?? "remote-acceptance-evidence";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "refrigeration-layout.remote.e2e.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 240_000,
  expect: {
    timeout: 25_000,
  },
  reporter: [
    ["line"],
    ["html", { outputFolder: path.join(evidenceDirectory, "playwright-report"), open: "never" }],
  ],
  outputDir: path.join(evidenceDirectory, "test-results"),
  use: {
    baseURL: dashboardUrl,
    headless: process.env.NEXOLAB_REMOTE_HEADLESS !== "false",
    ignoreHTTPSErrors: false,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium-tailscale-production",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
