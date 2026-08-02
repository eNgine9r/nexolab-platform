import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

const evidenceDirectory = process.env.NEXOLAB_OBSERVABILITY_EVIDENCE_DIR ?? "test-results-observability";
const grafanaUrl = process.env.NEXOLAB_OBSERVABILITY_GRAFANA_URL ?? "http://127.0.0.1:13030";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "observability.production.e2e.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: {
    timeout: 20_000,
  },
  reporter: [["line"]],
  outputDir: path.join(evidenceDirectory, "browser-test-results"),
  use: {
    baseURL: grafanaUrl,
    headless: true,
    screenshot: "only-on-failure",
    trace: "off",
    video: "off",
  },
  projects: [
    {
      name: "chromium-grafana-operator-dashboard",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
