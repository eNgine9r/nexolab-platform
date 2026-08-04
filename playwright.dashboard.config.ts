import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

const evidenceDirectory = process.env.NEXOLAB_DASHBOARD_EVIDENCE_DIR ?? "dashboard-acceptance-evidence";
const webUrl = process.env.NEXOLAB_DASHBOARD_WEB_URL ?? "http://127.0.0.1:13020";
const webPort = new URL(webUrl).port || "13020";

// The focused registry flow runs first against the seeded organization and waits for its settled global total.
// Four existing authenticated regressions then reuse the same production stack and database.
export default defineConfig({
  testDir: "./e2e",
  testMatch: [
    "authenticated-dashboard.production.e2e.ts",
    "energy.production.e2e.ts",
    "live.production.e2e.ts",
    "equipment-layouts.production.e2e.ts",
    "equipment-registry.production.e2e.ts",
  ],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180_000,
  expect: {
    timeout: 20_000,
  },
  reporter: [
    ["line"],
    [
      "html",
      {
        outputFolder: path.join(evidenceDirectory, "playwright-report"),
        open: "never",
      },
    ],
  ],
  outputDir: path.join(evidenceDirectory, "test-results"),
  use: {
    baseURL: webUrl,
    headless: true,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "equipment-registry-production",
      testMatch: "equipment-registry.production.e2e.ts",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "chromium-authenticated-dashboard",
      testIgnore: "equipment-registry.production.e2e.ts",
      dependencies: ["equipment-registry-production"],
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: `npm run start -- --hostname 127.0.0.1 --port ${webPort}`,
    url: webUrl,
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
    stdout: "pipe",
    stderr: "pipe",
  },
});
