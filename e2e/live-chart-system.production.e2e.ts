import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";

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
const webUrl = process.env.NEXOLAB_DASHBOARD_WEB_URL ?? "http://127.0.0.1:13020";

type ObservedRequest = { url: string; method: string };
type SocketEvidence = { opened: number; closed: number; active: number; maximum: number };

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

function seedExplorerTelemetry(): { equipmentId: string; channels: string[] } {
  const suffix = `${Date.now()}-${randomUUID().slice(0, 8)}`;
  const equipmentId = `ISSUE400-${suffix}`;
  const channels = Array.from({ length: 8 }, (_, index) =>
    index < 6 ? `issue400-temp-${index + 1}` : `issue400-voltage-${index - 5}`,
  );
  const now = Date.now();
  const values: string[] = [];

  for (let index = 0; index < channels.length; index += 1) {
    const temperature = index < 6;
    const metric = temperature ? "temperature.probe" : "electrical.voltage";
    const unit = temperature ? "degC" : "V";
    const baseValue = temperature ? 2.5 + index : 228 + index;
    for (let sampleIndex = 0; sampleIndex < 4; sampleIndex += 1) {
      const capturedAt = new Date(now - (3 - sampleIndex) * 30_000).toISOString();
      const value = baseValue + sampleIndex * 0.1;
      const communicationGap = index === 0 && sampleIndex === 2;
      const alarmContextWithoutDomainEvent = index === 0 && sampleIndex === 3;
      values.push(`(
        ${sqlString(randomUUID())},
        'edge-live-issue-400',
        ${sqlString(capturedAt)}::timestamptz,
        ${sqlString(metric)},
        ${communicationGap ? "NULL" : value},
        ${sqlString(unit)},
        ${communicationGap ? "'communication_error'" : "'valid'"},
        'issue-451-acceptance',
        ${sqlString(equipmentId)},
        ${sqlString(channels[index])},
        ${alarmContextWithoutDomainEvent ? "'high'" : "NULL"},
        ${communicationGap ? "NULL" : Math.round(value * 10)},
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
  return { equipmentId, channels };
}

function cleanupExplorerTelemetry(equipmentId: string): void {
  postgres(`
DELETE FROM telemetry_latest WHERE equipment_id = ${sqlString(equipmentId)};
DELETE FROM telemetry_samples WHERE equipment_id = ${sqlString(equipmentId)};
`);
}

function observeRuntime(page: Page): {
  telemetry: ObservedRequest[];
  acquisitionMutations: ObservedRequest[];
  publicRequests: ObservedRequest[];
  sockets: SocketEvidence;
} {
  const telemetry: ObservedRequest[] = [];
  const acquisitionMutations: ObservedRequest[] = [];
  const publicRequests: ObservedRequest[] = [];
  const sockets: SocketEvidence = { opened: 0, closed: 0, active: 0, maximum: 0 };
  const allowedHosts = new Set([new URL(webUrl).host, new URL(apiBaseUrl).host]);

  page.on("request", (request) => {
    const observed = { url: request.url(), method: request.method() };
    const url = new URL(observed.url);
    const pathname = url.pathname.toLowerCase();
    if (pathname.includes("/api/v1/telemetry/")) telemetry.push(observed);
    const mutating = !["GET", "HEAD", "OPTIONS"].includes(observed.method);
    const acquisitionPath =
      pathname.includes("device-agent") ||
      pathname.includes("/discovery") ||
      pathname.includes("/configuration") ||
      pathname.includes("/config/");
    if (mutating && acquisitionPath) acquisitionMutations.push(observed);
    if (url.protocol === "http:" || url.protocol === "https:") {
      if (!allowedHosts.has(url.host)) publicRequests.push(observed);
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

  return { telemetry, acquisitionMutations, publicRequests, sockets };
}

async function assertNoPageOverflow(page: Page): Promise<void> {
  await expect
    .poll(() =>
      page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      })),
    )
    .toMatchObject({ scrollWidth: await page.evaluate(() => document.documentElement.clientWidth) });
}

test("Live Data uses the canonical synchronized Chart System without acquisition side effects", async ({
  browser,
}) => {
  mkdirSync(evidenceDirectory, { recursive: true });
  const fixture = seedExplorerTelemetry();
  const context = await authenticatedContext(browser);
  const page = await context.newPage();
  const runtime = observeRuntime(page);

  try {
    await page.goto("/live?workspace=explorer", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Live дані", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Saved Dashboards" })).toBeVisible();

    const primaryChart = page.getByTestId("live-primary-chart");
    const filterPanel = page.getByTestId("live-filter-panel");
    const inventoryPanel = page.getByTestId("live-inventory-panel");
    await expect(primaryChart).toBeVisible();
    await expect(primaryChart.getByText("Жодного каналу не обрано", { exact: true })).toBeVisible();
    await expect(
      primaryChart.getByText("Оберіть канали нижче у Latest values", { exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(() => {
        const chart = document.querySelector('[data-testid="live-primary-chart"]');
        const filters = document.querySelector('[data-testid="live-filter-panel"]');
        const inventory = document.querySelector('[data-testid="live-inventory-panel"]');
        if (!chart || !filters || !inventory) return false;
        return (
          Boolean(chart.compareDocumentPosition(filters) & Node.DOCUMENT_POSITION_FOLLOWING) &&
          Boolean(filters.compareDocumentPosition(inventory) & Node.DOCUMENT_POSITION_FOLLOWING)
        );
      }),
    ).toBe(true);
    expect(runtime.telemetry.filter((request) => request.url.includes("/history"))).toEqual([]);

    const search = page.getByPlaceholder("node, equipment, channel, metric, source...");
    await search.fill(fixture.equipmentId);
    const compare = page.getByRole("checkbox", { name: /Порівнювати/ });
    expect(
      await page.evaluate(() => {
        const chartButton = document.querySelector('[data-testid="live-primary-chart"] button');
        const searchInput = document.querySelector(
          'input[placeholder="node, equipment, channel, metric, source..."]',
        );
        const compareInput = document.querySelector(
          '[data-testid="live-inventory-panel"] input[type="checkbox"]',
        );
        if (!chartButton || !searchInput || !compareInput) return false;
        return (
          Boolean(chartButton.compareDocumentPosition(searchInput) & Node.DOCUMENT_POSITION_FOLLOWING) &&
          Boolean(searchInput.compareDocumentPosition(compareInput) & Node.DOCUMENT_POSITION_FOLLOWING)
        );
      }),
    ).toBe(true);
    await expect(compare).toHaveCount(8);
    for (let index = 0; index < 8; index += 1) await compare.nth(index).check();

    await expect(page.getByText("8 / 8", { exact: true })).toBeVisible();
    await expect(page.getByTestId("live-selected-context")).toContainText(fixture.equipmentId);
    await expect(page.getByTestId("live-selected-context")).toContainText(fixture.channels[0]);
    await expect(
      page.getByRole("heading", { name: `Live Data · ${fixture.equipmentId}`, exact: true }),
    ).toBeVisible();
    const summary = page.getByTestId("chart-accessible-summary");
    await expect(summary).toHaveCount(1);
    await expect(summary).toContainText("Range Live");
    await expect(summary).toContainText("8 series visible");
    await expect(summary).toContainText("Axes 2");
    await expect(summary).toContainText("degC");
    await expect(summary).toContainText("V");
    await expect(summary).toContainText("Continuity breaks 1");
    await expect(page.getByText(/Alarm context/)).toHaveCount(0);

    const rendererHosts = page.getByTestId("chart-renderer-host");
    await expect(rendererHosts).toHaveCount(1);
    const equipmentHost = rendererHosts.first();
    await equipmentHost.scrollIntoViewIfNeeded();
    const equipmentBox = await equipmentHost.boundingBox();
    if (!equipmentBox) throw new Error("Equipment chart host has no bounding box");
    await page.mouse.move(
      equipmentBox.x + equipmentBox.width * 0.72,
      equipmentBox.y + equipmentBox.height * 0.5,
    );
    const inspector = page.getByTestId("chart-inspector").first();
    await expect(inspector).toContainText("Nearest measured sample per visible series");
    await expect(inspector.getByRole("row")).toHaveCount(9);
    for (const channelId of fixture.channels) await expect(inspector).toContainText(channelId);
    await expect(inspector).toContainText(/\d+\.\d{2} degC/);
    await expect(inspector).toContainText(/\d+\.\d{2} V/);

    const historyRequestsBeforeLivePoint = runtime.telemetry.filter((request) =>
      request.url.includes("/history"),
    ).length;

    publishExplorerSample(fixture.equipmentId, fixture.channels[0], 9.876);
    await expect(page.getByText("9.88 degC", { exact: true }).first()).toBeVisible();
    await expect(rendererHosts).toHaveCount(1);
    await expect(page.getByText("Завантаження history window за одним ingestion watermark…")).toHaveCount(0);
    await expect
      .poll(() => runtime.telemetry.filter((request) => request.url.includes("/history")).length)
      .toBe(historyRequestsBeforeLivePoint);

    await expect.poll(() => runtime.sockets.maximum).toBe(1);
    expect(runtime.acquisitionMutations).toEqual([]);
    expect(runtime.publicRequests).toEqual([]);
    expect(runtime.telemetry.some((request) => request.url.includes("/latest"))).toBe(true);
    expect(runtime.telemetry.some((request) => request.url.includes("/history"))).toBe(true);
    expect(
      runtime.telemetry
        .filter((request) => request.url.includes("/history"))
        .every((request) => {
          const channelId = new URL(request.url).searchParams.get("channel_id");
          return channelId !== null && fixture.channels.includes(channelId);
        }),
    ).toBe(true);

    await page.getByRole("button", { name: "Hide" }).first().click();
    await expect(page.getByRole("button", { name: "Show" }).first()).toBeVisible();
    await expect(summary).toContainText("7 series visible");
    await expect(summary).toContainText("Axes 2");
    await page.getByRole("button", { name: "Show" }).first().click();
    await expect(summary).toContainText("8 series visible");
    await page.getByRole("button", { name: "Solo" }).first().click();
    await expect(summary).toContainText("1 series visible");
    await expect(summary).toContainText("Axes 1");
    await expect(inspector.getByRole("row")).toHaveCount(2);
    await expect(page.getByRole("button", { name: "Reset zoom" })).toHaveCount(1);

    await page.getByRole("button", { name: "5 min", exact: true }).click();
    await expect(summary).toContainText("Range 5 min");
    await page.getByRole("button", { name: "Return to Live", exact: true }).click();
    await expect(page.getByText("Live Follow", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Pause View", exact: true }).click();
    await expect(page.getByText("Paused view", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Return to Live", exact: true }).click();

    for (const viewport of [
      { width: 360, height: 800 },
      { width: 1440, height: 900 },
      { width: 1920, height: 1080 },
    ]) {
      await page.setViewportSize(viewport);
      await assertNoPageOverflow(page);
      const regionOrder = await page.evaluate(() => {
        const chart = document.querySelector('[data-testid="live-primary-chart"]');
        const filters = document.querySelector('[data-testid="live-filter-panel"]');
        const inventory = document.querySelector('[data-testid="live-inventory-panel"]');
        if (
          !(chart instanceof HTMLElement) ||
          !(filters instanceof HTMLElement) ||
          !(inventory instanceof HTMLElement)
        ) {
          return null;
        }
        return {
          chartTop: chart.getBoundingClientRect().top,
          filterTop: filters.getBoundingClientRect().top,
          inventoryTop: inventory.getBoundingClientRect().top,
        };
      });
      expect(regionOrder).not.toBeNull();
      expect(regionOrder!.chartTop).toBeLessThan(regionOrder!.filterTop);
      expect(regionOrder!.filterTop).toBeLessThan(regionOrder!.inventoryTop);
    }

    await page.getByRole("button", { name: "Saved Dashboards", exact: true }).click();
    await expect(page.getByRole("button", { name: "Saved Dashboards", exact: true })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await page.getByRole("button", { name: "Live Data", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Live дані", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Live Data", exact: true })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await expect.poll(() => runtime.sockets.active).toBeLessThanOrEqual(1);
    expect(runtime.sockets.maximum).toBeLessThanOrEqual(1);
    expect(runtime.acquisitionMutations).toEqual([]);
    expect(runtime.publicRequests).toEqual([]);

    await page.screenshot({
      path: path.join(evidenceDirectory, "live-chart-system-1920.png"),
      fullPage: true,
    });
    writeFileSync(
      path.join(evidenceDirectory, "live-chart-system-summary.json"),
      `${JSON.stringify(
        {
          equipmentId: fixture.equipmentId,
          channels: fixture.channels,
          telemetryRequests: runtime.telemetry,
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
    cleanupExplorerTelemetry(fixture.equipmentId);
  }
});

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for Live Chart System acceptance`);
  return value;
}
