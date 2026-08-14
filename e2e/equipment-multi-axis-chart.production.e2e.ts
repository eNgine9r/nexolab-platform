import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";

const organizationId = requiredEnvironment("NEXOLAB_DASHBOARD_ORGANIZATION_ID");
const sessionCredential = requiredEnvironment("NEXOLAB_DASHBOARD_VIEWER_TOKEN");
const composeProject = requiredEnvironment("COMPOSE_PROJECT_NAME");
const baseCompose = requiredEnvironment("NEXOLAB_DASHBOARD_BASE_COMPOSE");
const acceptanceCompose = requiredEnvironment("NEXOLAB_DASHBOARD_ACCEPTANCE_COMPOSE");
const postgresUser = requiredEnvironment("POSTGRES_USER");
const postgresDatabase = requiredEnvironment("POSTGRES_DB");
const apiBaseUrl = requiredEnvironment("NEXT_PUBLIC_NEXOLAB_API_BASE_URL");
const evidenceDirectory = process.env.NEXOLAB_DASHBOARD_EVIDENCE_DIR ?? "dashboard-acceptance-evidence";
const webUrl = process.env.NEXOLAB_DASHBOARD_WEB_URL ?? "http://127.0.0.1:13020";

type ObservedRequest = { url: string; method: string };
type SocketEvidence = { opened: number; closed: number; active: number; maximum: number };

type MeterChannel = {
  channelId: string;
  metric: string;
  unit: "V" | "A" | "W";
  baseValue: number;
};

const CHANNELS: readonly MeterChannel[] = [
  { channelId: "meter-voltage", metric: "electrical.voltage", unit: "V", baseValue: 230.4 },
  { channelId: "meter-current", metric: "electrical.current", unit: "A", baseValue: 2.4 },
  { channelId: "meter-power", metric: "electrical.active_power", unit: "W", baseValue: 548.2 },
];

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`Missing required environment variable ${name}`);
  return value;
}

async function authenticatedContext(browser: Browser): Promise<BrowserContext> {
  const context = await browser.newContext();
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

function seedMixedUnitMeter(): string {
  const equipmentId = `ISSUE453-METER-${Date.now()}-${randomUUID().slice(0, 8)}`;
  const now = Date.now();
  const values: string[] = [];

  for (const [channelIndex, channel] of CHANNELS.entries()) {
    for (let sampleIndex = 0; sampleIndex < 4; sampleIndex += 1) {
      const capturedAt = new Date(now - (3 - sampleIndex) * 30_000).toISOString();
      const value = channel.baseValue + sampleIndex * (channelIndex + 1) * 0.1;
      values.push(`(
        ${sqlString(randomUUID())},
        'edge-live-issue-453',
        ${sqlString(capturedAt)}::timestamptz,
        ${sqlString(channel.metric)},
        ${value},
        ${sqlString(channel.unit)},
        'valid',
        'issue-453-acceptance',
        ${sqlString(equipmentId)},
        ${sqlString(channel.channelId)},
        NULL,
        ${Math.round(value * 10)},
        NULL,
        '{}'::json
      )`);
    }
  }

  postgres(`
INSERT INTO telemetry_samples (
  event_id, node_id, captured_at, metric, value, unit, quality, source,
  equipment_id, channel_id, alarm, raw_value, raw_status, raw_payload
)
VALUES ${values.join(",\n")};

INSERT INTO telemetry_latest (
  sample_id, event_id, node_id, captured_at, metric, value, unit, quality, source,
  equipment_id, channel_id, alarm, raw_value, raw_status, stale_after_seconds, received_at
)
SELECT DISTINCT ON (node_id, equipment_id, channel_id, metric)
  id, event_id, node_id, captured_at, metric, value, unit, quality, source,
  equipment_id, channel_id, alarm, raw_value, raw_status, NULL, received_at
FROM telemetry_samples
WHERE equipment_id = ${sqlString(equipmentId)}
ORDER BY node_id, equipment_id, channel_id, metric, captured_at DESC, id DESC;
`);

  return equipmentId;
}

function cleanupMixedUnitMeter(equipmentId: string): void {
  postgres(`
DELETE FROM telemetry_latest WHERE equipment_id = ${sqlString(equipmentId)};
DELETE FROM telemetry_samples WHERE equipment_id = ${sqlString(equipmentId)};
`);
}

function observeRuntime(page: Page): {
  acquisitionMutations: ObservedRequest[];
  publicRequests: ObservedRequest[];
  sockets: SocketEvidence;
} {
  const acquisitionMutations: ObservedRequest[] = [];
  const publicRequests: ObservedRequest[] = [];
  const sockets: SocketEvidence = { opened: 0, closed: 0, active: 0, maximum: 0 };
  const allowedHosts = new Set([new URL(webUrl).host, new URL(apiBaseUrl).host]);

  page.on("request", (request) => {
    const observed = { url: request.url(), method: request.method() };
    const url = new URL(observed.url);
    const pathname = url.pathname.toLowerCase();
    const mutating = !["GET", "HEAD", "OPTIONS"].includes(observed.method);
    const acquisitionPath =
      pathname.includes("device-agent") ||
      pathname.includes("/discovery") ||
      pathname.includes("/configuration") ||
      pathname.includes("/config/");
    if (mutating && acquisitionPath) acquisitionMutations.push(observed);
    if ((url.protocol === "http:" || url.protocol === "https:") && !allowedHosts.has(url.host)) {
      publicRequests.push(observed);
    }
  });

  page.on("websocket", (socket) => {
    sockets.opened += 1;
    sockets.active += 1;
    sockets.maximum = Math.max(sockets.maximum, sockets.active);
    socket.on("close", () => {
      sockets.closed += 1;
      sockets.active = Math.max(0, sockets.active - 1);
    });
  });

  return { acquisitionMutations, publicRequests, sockets };
}

async function assertNoPageOverflow(page: Page): Promise<void> {
  await expect
    .poll(() =>
      page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      })),
    )
    .toEqual({
      scrollWidth: await page.evaluate(() => document.documentElement.clientWidth),
      clientWidth: await page.evaluate(() => document.documentElement.clientWidth),
    });
}

test("one equipment renders V/A/W on one synchronized multi-axis canvas", async ({ browser }) => {
  mkdirSync(evidenceDirectory, { recursive: true });
  const equipmentId = seedMixedUnitMeter();
  const context = await authenticatedContext(browser);
  const page = await context.newPage();
  const runtime = observeRuntime(page);

  try {
    await page.goto("/live?workspace=explorer", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Live дані", exact: true })).toBeVisible();

    const search = page.getByPlaceholder("node, equipment, channel, metric, source...");
    await search.fill(equipmentId);
    const compare = page.getByRole("checkbox", { name: /Порівнювати/ });
    await expect(compare).toHaveCount(CHANNELS.length);
    for (let index = 0; index < CHANNELS.length; index += 1) await compare.nth(index).check();

    await expect(page.getByText("3 / 8", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: `Live Data · ${equipmentId}`, exact: true })).toHaveCount(
      1,
    );

    const summary = page.getByTestId("chart-accessible-summary");
    await expect(summary).toHaveCount(1);
    await expect(summary).toContainText("3 series visible");
    await expect(summary).toContainText("Axes 3");
    for (const unit of ["V", "A", "W"]) await expect(summary).toContainText(unit);

    const rendererHost = page.getByTestId("chart-renderer-host");
    await expect(rendererHost).toHaveCount(1);
    await rendererHost.scrollIntoViewIfNeeded();
    const box = await rendererHost.boundingBox();
    if (!box) throw new Error("Mixed-unit chart host has no bounding box");
    await page.mouse.move(box.x + box.width * 0.72, box.y + box.height * 0.5);

    const inspector = page.getByTestId("chart-inspector");
    await expect(inspector).toContainText("Nearest measured sample per visible series");
    await expect(inspector.getByRole("row")).toHaveCount(CHANNELS.length + 1);
    for (const channel of CHANNELS) {
      await expect(inspector).toContainText(channel.channelId);
      await expect(inspector).toContainText(channel.unit);
    }

    await page.getByRole("button", { name: "Hide" }).first().click();
    await expect(summary).toContainText("2 series visible");
    await expect(summary).toContainText("Axes 2");
    await page.getByRole("button", { name: "Show" }).first().click();
    await expect(summary).toContainText("3 series visible");
    await expect(summary).toContainText("Axes 3");

    await page.getByRole("button", { name: "Solo" }).first().click();
    await expect(summary).toContainText("1 series visible");
    await expect(summary).toContainText("Axes 1");
    await expect(inspector.getByRole("row")).toHaveCount(2);

    for (const viewport of [
      { width: 360, height: 800 },
      { width: 1440, height: 900 },
      { width: 1920, height: 1080 },
    ]) {
      await page.setViewportSize(viewport);
      await assertNoPageOverflow(page);
    }

    await expect.poll(() => runtime.sockets.maximum).toBeLessThanOrEqual(1);
    expect(runtime.acquisitionMutations).toEqual([]);
    expect(runtime.publicRequests).toEqual([]);

    await page.screenshot({
      path: path.join(evidenceDirectory, "issue-453-mixed-unit-chart-1920.png"),
      fullPage: true,
    });
    writeFileSync(
      path.join(evidenceDirectory, "issue-453-mixed-unit-chart-summary.json"),
      `${JSON.stringify(
        {
          equipmentId,
          channels: CHANNELS,
          websocket: runtime.sockets,
          acquisitionMutations: runtime.acquisitionMutations,
          publicRequests: runtime.publicRequests,
        },
        null,
        2,
      )}\n`,
    );
  } finally {
    await context.close();
    cleanupMixedUnitMeter(equipmentId);
  }
});
