import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

const evidenceDirectory = process.env.NEXOLAB_RBAC_EVIDENCE_DIR ?? "rbac-acceptance-evidence";
const webUrl = process.env.NEXOLAB_RBAC_WEB_URL ?? "http://127.0.0.1:23000";
const webPort = new URL(webUrl).port || "23000";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "auth-rbac.production.e2e.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 20_000 },
  reporter: [
    ["line"],
    ["html", { outputFolder: path.join(evidenceDirectory, "playwright-report"), open: "never" }],
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
      name: "chromium-rbac",
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
