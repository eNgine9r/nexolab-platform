import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Browser, type BrowserContext } from "@playwright/test";

// Runs as its own Playwright project after every other dashboard spec (playwright.dashboard.config.ts):
// it loads the shared stack heavily for minutes, which must not change what the other specs see.
const organizationId = requiredEnvironment("NEXOLAB_DASHBOARD_ORGANIZATION_ID");
const sessionCredential = requiredEnvironment("NEXOLAB_DASHBOARD_VIEWER_TOKEN");
const evidenceDirectory = process.env.NEXOLAB_DASHBOARD_EVIDENCE_DIR ?? "dashboard-acceptance-evidence";
const composeProject = requiredEnvironment("COMPOSE_PROJECT_NAME");
const baseCompose = requiredEnvironment("NEXOLAB_DASHBOARD_BASE_COMPOSE");
const acceptanceCompose = requiredEnvironment("NEXOLAB_DASHBOARD_ACCEPTANCE_COMPOSE");
const postgresUser = requiredEnvironment("POSTGRES_USER");
const postgresDatabase = requiredEnvironment("POSTGRES_DB");
const apiBaseUrl = requiredEnvironment("NEXT_PUBLIC_NEXOLAB_API_BASE_URL");
const mqttTopic = process.env.MQTT_TOPIC ?? "nexolab/telemetry";

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for chart performance evidence`);
  return value;
}

async function authenticatedContext(browser: Browser, timeZone = "UTC"): Promise<BrowserContext> {
  const context = await browser.newContext({ timezoneId: timeZone });
  await context.addInitScript(
    ({ accessToken, organization }) => {
      if (window.location.protocol === "about:") return;
      window.sessionStorage.setItem("nexolab.acceptance.access-token", accessToken);
      window.sessionStorage.setItem("nexolab.acceptance.organization-id", organization);
    },
    { accessToken: sessionCredential, organization: organizationId },
  );
  return context;
}

function compose(args: string[]): string {
  return execFileSync(
    "docker",
    [
      "compose",
      "--project-name",
      composeProject,
      "--file",
      baseCompose,
      "--file",
      acceptanceCompose,
      ...args,
    ],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
  );
}

function postgres(sql: string): string {
  return compose([
    "exec",
    "-T",
    "postgres",
    "psql",
    "-U",
    postgresUser,
    "-d",
    postgresDatabase,
    "-v",
    "ON_ERROR_STOP=1",
    "-tAc",
    sql,
  ]);
}

function sqlString(value: string): string {
  return `'${value.replaceAll("'", "''")}'`;
}

function publishExplorerSample(equipmentId: string, channelId: string, value: number): void {
  const payload = JSON.stringify({
    event_id: randomUUID(),
    node_id: "edge-live-issue-400",
    captured_at: new Date().toISOString(),
    metric: "temperature.probe",
    value,
    unit: "degC",
    quality: "valid",
    source: "issue-406-regression",
    equipment_id: equipmentId,
    channel_id: channelId,
    alarm: null,
    raw_value: Math.round(value * 10),
    raw_status: null,
  });

  execFileSync(
    "docker",
    [
      "compose",
      "--project-name",
      composeProject,
      "--file",
      baseCompose,
      "--file",
      acceptanceCompose,
      "exec",
      "-T",
      "mqtt",
      "mosquitto_pub",
      "-h",
      "127.0.0.1",
      "-t",
      mqttTopic,
      "-m",
      payload,
    ],
    { stdio: "pipe" },
  );
}

/**
 * #1813 browser performance evidence: Live Data with 24 channels x 24 h of 10 s history (207 384
 * PostgreSQL rows), once through the aggregated backend and once through the raw fallback that the
 * current site backend uses (aggregate endpoint answered 404). Metrics are written to the
 * acceptance evidence directory; the same spec runs unchanged on the pre-#1804 frontend for the
 * before/after comparison, so it only relies on long-standing selectors.
 */
test("Live Data 24-channel 24 h history performance evidence (#1813)", async ({ browser }) => {
  test.setTimeout(600_000);
  const suffix = `${Date.now()}-${randomUUID().slice(0, 8)}`;
  const nodeId = "edge-perf-1813";
  const equipmentId = `PERF1813-${suffix}`;
  const channelCount = 24;
  const now = Date.now();
  postgres(`
INSERT INTO telemetry_samples (
  event_id, node_id, captured_at, metric, value, unit, quality, source,
  equipment_id, channel_id, alarm, raw_value, raw_status, raw_payload
)
SELECT gen_random_uuid()::text, ${sqlString(nodeId)},
       to_timestamp(${Math.floor(now / 1000)} - step * 10),
       'temperature',
       CASE WHEN step % 997 = 13 THEN NULL
            WHEN step % 1201 = 600 THEN 25 + channel
            ELSE round((4 + sin(step / 360.0) + ((step * 7919) % 10) / 20.0)::numeric, 2)::float8 END,
       'degC',
       CASE WHEN step % 997 = 13 THEN 'communication_error' ELSE 'valid' END,
       'perf-1813', ${sqlString(equipmentId)}, 'perf-' || channel, NULL, 0, NULL, '{}'::json
FROM generate_series(1, ${channelCount}) AS channel, generate_series(0, 8640) AS step
WHERE NOT (step BETWEEN 3000 AND 3030);

INSERT INTO telemetry_latest (
  sample_id, event_id, node_id, captured_at, metric, value, unit, quality, source,
  equipment_id, channel_id, alarm, raw_value, raw_status, stale_after_seconds, received_at
)
SELECT DISTINCT ON (node_id, equipment_id, channel_id, metric)
  id, event_id, node_id, captured_at, metric, value, unit, quality, source,
  equipment_id, channel_id, alarm, raw_value, raw_status, NULL, received_at
FROM telemetry_samples
WHERE equipment_id = ${sqlString(equipmentId)} AND quality = 'valid'
ORDER BY node_id, equipment_id, channel_id, metric, captured_at DESC, id DESC;
ANALYZE telemetry_samples;
`);
  const keys = Array.from({ length: channelCount }, (_, index) =>
    [nodeId, equipmentId, `perf-${index + 1}`, "temperature", "degC"].map(encodeURIComponent).join("|"),
  );
  const query = `${keys.map((key) => `compare=${encodeURIComponent(key)}`).join("&")}&range=24h`;
  const results: Record<string, unknown>[] = [];

  try {
    for (const mode of ["aggregate-backend", "raw-fallback"] as const) {
      const context = await authenticatedContext(browser);
      await context.addInitScript(() => {
        const perf = { longTasks: [] as Array<[number, number]>, frames: [] as number[], running: false };
        Reflect.set(window, "__nexolabPerf1813", perf);
        try {
          new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) perf.longTasks.push([entry.startTime, entry.duration]);
          }).observe({ type: "longtask", buffered: true });
        } catch {
          // Long-task timing is unavailable in this browser; frame timing still applies.
        }
      });
      const page = await context.newPage();
      if (mode === "raw-fallback") {
        await page.route("**/api/v1/telemetry/history/aggregate**", (route) =>
          route.fulfill({ status: 404, contentType: "application/json", body: '{"detail":"Not Found"}' }),
        );
      }
      const traffic = { history: 0, aggregate: 0, historyBytes: 0, failed: 0, cancelled: 0 };
      page.on("requestfinished", async (request) => {
        const pathname = new URL(request.url()).pathname;
        if (!pathname.includes("/api/v1/telemetry/history")) return;
        if (pathname.endsWith("/history/aggregate")) traffic.aggregate += 1;
        else traffic.history += 1;
        const sizes = await request.sizes().catch(() => null);
        traffic.historyBytes += sizes?.responseBodySize ?? 0;
      });
      page.on("requestfailed", (request) => {
        if (!new URL(request.url()).pathname.includes("/api/v1/telemetry/history")) return;
        // A superseded viewport/statistics request is aborted on purpose (#1813).
        if (/ERR_ABORTED|aborted/i.test(request.failure()?.errorText ?? "")) traffic.cancelled += 1;
        else traffic.failed += 1;
      });

      const startedAt = Date.now();
      await page.goto(`/live?${query}`, { waitUntil: "domcontentloaded" });
      // Ingestion must not degrade while history loads: publish one sample now and time its
      // persistence (raw fallback sends hundreds of pages; the aggregate backend a few requests).
      const probeChannel = `perf-probe-${mode}`;
      const probeStartedAt = Date.now();
      publishExplorerSample(equipmentId, probeChannel, 7.5);
      const hosts = page.getByTestId("chart-renderer-host");
      await expect(hosts.first()).toBeVisible({ timeout: 240_000 });
      // Charts render only after the whole history window is loaded (old and new frontends alike).
      await expect(page.getByText("Завантаження history window", { exact: false })).toHaveCount(0, {
        timeout: 240_000,
      });
      const firstChartMs = Date.now() - startedAt;
      let ingestMs: number | null = null;
      for (let attempt = 0; attempt < 120; attempt += 1) {
        const persisted = postgres(
          `SELECT 'PROBE=' || count(*) FROM telemetry_samples WHERE equipment_id = ${sqlString(equipmentId)} AND channel_id = ${sqlString(probeChannel)};`,
        );
        if (persisted.includes("PROBE=1")) {
          ingestMs = Date.now() - probeStartedAt;
          break;
        }
        await page.waitForTimeout(250);
      }

      const surface = page.getByTestId("chart-renderer-surface").first();
      await surface.scrollIntoViewIfNeeded();
      const box = (await surface.boundingBox())!;
      await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.5);
      await page.evaluate(() => {
        const perf = Reflect.get(window, "__nexolabPerf1813") as { frames: number[]; running: boolean };
        perf.frames = [];
        perf.running = true;
        const tick = (time: number) => {
          if (!perf.running) return;
          perf.frames.push(time);
          requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      });
      const interactionStartedAt = await page.evaluate(() => performance.now());
      for (let step = 0; step < 10; step += 1) {
        await page.mouse.wheel(0, -240);
        await page.waitForTimeout(40);
      }
      for (let pan = 0; pan < 3; pan += 1) {
        await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.5);
        await page.mouse.down({ button: "left" });
        await page.mouse.move(box.x + box.width * 0.3, box.y + box.height * 0.5, { steps: 12 });
        await page.mouse.up({ button: "left" });
      }
      await page.waitForTimeout(600);
      const interaction = await page.evaluate((since) => {
        const perf = Reflect.get(window, "__nexolabPerf1813") as {
          frames: number[];
          running: boolean;
          longTasks: Array<[number, number]>;
        };
        perf.running = false;
        const gaps = perf.frames
          .slice(1)
          .map((time, index) => time - perf.frames[index])
          .sort((a, b) => a - b);
        const during = perf.longTasks.filter(([start]) => start >= since);
        const durationMs = perf.frames.length > 1 ? perf.frames.at(-1)! - perf.frames[0] : 0;
        return {
          frames: perf.frames.length,
          averageFps:
            durationMs > 0 ? Math.round(((perf.frames.length - 1) * 1000 * 10) / durationMs) / 10 : null,
          p95FrameMs: gaps.length ? Math.round(gaps[Math.floor(gaps.length * 0.95)] * 10) / 10 : null,
          maxFrameMs: gaps.length ? Math.round(gaps.at(-1)! * 10) / 10 : null,
          longTasks: during.length,
          longTaskTotalMs: Math.round(during.reduce((sum, [, duration]) => sum + duration, 0)),
          longTaskMaxMs: Math.round(Math.max(0, ...during.map(([, duration]) => duration))),
        };
      }, interactionStartedAt);
      const workspace = page.getByTestId("live-chart-workspace");
      const detail =
        (await workspace.count()) > 0 ? await workspace.getAttribute("data-viewport-detail") : null;
      const source =
        (await workspace.count()) > 0 ? await workspace.getAttribute("data-history-source") : null;
      const heap = await page.evaluate(() => {
        const memory = Reflect.get(performance, "memory") as { usedJSHeapSize?: number } | undefined;
        return memory?.usedJSHeapSize ? Math.round(memory.usedJSHeapSize / 1_048_576) : null;
      });
      const result = {
        mode,
        channels: channelCount,
        range: "24h",
        rowsPerChannel: 8_610,
        firstChartMs,
        historyRequests: traffic.history,
        aggregateRequests: traffic.aggregate,
        historyMegabytes: Math.round((traffic.historyBytes / 1_048_576) * 10) / 10,
        failedHistoryRequests: traffic.failed,
        cancelledHistoryRequests: traffic.cancelled,
        ingestDuringLoadMs: ingestMs,
        heapMegabytes: heap,
        historySource: source,
        viewportDetailPoints: detail,
        interaction,
      };
      results.push(result);
      console.log(`#1813 performance ${JSON.stringify(result)}`);
      expect(traffic.failed).toBe(0);
      expect(ingestMs).not.toBeNull();
      await context.close();
    }
  } finally {
    mkdirSync(evidenceDirectory, { recursive: true });
    writeFileSync(
      path.join(evidenceDirectory, "chart-performance-1813.json"),
      `${JSON.stringify({ commit: process.env.GITHUB_SHA ?? null, results }, null, 2)}\n`,
    );
    postgres(`
DELETE FROM telemetry_latest WHERE equipment_id = ${sqlString(equipmentId)};
DELETE FROM telemetry_samples WHERE equipment_id = ${sqlString(equipmentId)};
ANALYZE telemetry_samples;
`);
    // Leave the shared stack settled for the next specs: readiness must answer quickly again.
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const started = Date.now();
      const ready = await fetch(new URL("/health/ready", apiBaseUrl)).catch(() => null);
      if (ready?.ok && Date.now() - started < 300) break;
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  }
});
