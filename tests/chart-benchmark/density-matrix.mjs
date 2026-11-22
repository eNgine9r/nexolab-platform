// #1620 density matrix: initial Canvas render of N series x P points in headless Chromium using the
// chart benchmark harness, plus the cost of reducing 30 000 raw points to that budget.
//
//   node tests/chart-benchmark/density-matrix.mjs [output.json]
//
// Local only (development tool): starts a throwaway Vite server on 127.0.0.1:5199. It never touches
// the application runtime, telemetry, hardware or the network beyond loopback.
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";
import { createServer } from "vite";

const root = fileURLToPath(new URL(".", import.meta.url));
const alias = { "@": fileURLToPath(new URL("../../src", import.meta.url)) };
const server = await createServer({
  root,
  configFile: false,
  resolve: { alias },
  server: { host: "127.0.0.1", port: 5199, strictPort: true },
});
await server.listen();
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto("http://127.0.0.1:5199/");
  await page.waitForFunction(() => Boolean(window.nexolabChartBenchmark));
  const rows = [];
  for (const series of [1, 8, 24]) {
    for (const points of [240, 500, 1000, 2500, 5000]) {
      const result = await page.evaluate(
        ([s, p]) => window.nexolabChartBenchmark.runDensity(s, p, 7),
        [series, points],
      );
      const row = {
        series,
        points,
        aggregate: series * points,
        medianMs: Math.round(result.measurement.medianMs * 10) / 10,
        p95Ms: Math.round(result.measurement.p95Ms * 10) / 10,
        reduceMsFrom30000: Math.round(result.details.reduceMsFrom30000 * 10) / 10,
      };
      rows.push(row);
      console.log(JSON.stringify(row));
    }
  }
  const output = process.argv[2];
  if (output) {
    const userAgent = await page.evaluate(() => navigator.userAgent);
    writeFileSync(output, JSON.stringify({ userAgent, rows }, null, 2));
  }
  await page.evaluate(() => window.nexolabChartBenchmark.dispose());
} finally {
  await browser.close();
  await server.close();
}
