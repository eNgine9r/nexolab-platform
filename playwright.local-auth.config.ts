import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

const evidenceDirectory = process.env.NEXOLAB_LOCAL_AUTH_EVIDENCE_DIR ?? "local-auth-acceptance-evidence";
const webUrl = process.env.NEXOLAB_LOCAL_AUTH_WEB_URL ?? "http://127.0.0.1:13011";
const webPort = new URL(webUrl).port || "13011";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "local-auth.production.e2e.ts",
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
    viewport: { width: 1440, height: 900 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium-local-auth",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
      },
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
