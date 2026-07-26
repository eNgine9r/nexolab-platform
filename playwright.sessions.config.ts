import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

const evidenceDirectory = process.env.NEXOLAB_SESSIONS_EVIDENCE_DIR ?? "session-acceptance-evidence";
const webUrl = process.env.NEXOLAB_SESSIONS_WEB_URL ?? "http://127.0.0.1:13030";
const webPort = new URL(webUrl).port || "13030";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "test-sessions.production.e2e.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 240_000,
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
      name: "chromium-test-sessions",
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
