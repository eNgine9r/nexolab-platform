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

function publishSavedDashboardSample(dashboardId: string, channelId: string, value: number): void {
  const selection = postgres(`
SELECT metric || '|' || native_unit
FROM live_dashboard_items
WHERE dashboard_id = ${sqlString(dashboardId)}
  AND channel_id = ${sqlString(channelId)}
ORDER BY position
LIMIT 1;
`).trim();
  const [metric, unit] = selection.split("|");
  if (!metric || !unit) throw new Error("Saved Dashboard live-point identity was not found");

  const payload = JSON.stringify({
    event_id: randomUUID(),
    node_id: "edge-chart-404",
    captured_at: new Date().toISOString(),
    metric,
    value,
    unit,
    quality: "valid",
    source: "issue-404-visual-continuity-regression",
    equipment_id: "saved-dashboard-e2e",
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

function seedNoSampleChannel(): string {
  const channelRefId = randomUUID();
  const suffix = Date.now().toString();
  const channelId = `acceptance-no-sample-${suffix}`;
  const sourceChannelId = `acceptance-source-${suffix}`;
  const output = postgres(`
WITH candidate AS (
  SELECT
    channel.organization_id,
    channel.climate_chamber_id,
    channel.bus_id,
    channel.device_id,
    channel.metric_type,
    channel.unit,
    available.channel_number,
    (
      SELECT COALESCE(MAX(existing.logical_sensor_number), 0) + 1
      FROM measurement_channels AS existing
      WHERE existing.organization_id = channel.organization_id
    ) AS logical_sensor_number
  FROM measurement_channels AS channel
  CROSS JOIN LATERAL (
    SELECT slot AS channel_number
    FROM generate_series(1, 6) AS slot
    WHERE NOT EXISTS (
      SELECT 1
      FROM measurement_channels AS occupied
      WHERE occupied.device_id = channel.device_id
        AND occupied.channel_number = slot
    )
    ORDER BY slot
    LIMIT 1
  ) AS available
  WHERE channel.organization_id = ${sqlString(organizationId)}
    AND channel.status = 'active'
  ORDER BY channel.device_id, channel.channel_number
  LIMIT 1
)
INSERT INTO measurement_channels (
  id, organization_id, climate_chamber_id, bus_id, device_id, channel_id,
  source_channel_id, channel_number, logical_sensor_number, display_name,
  physical_sensor_count, metric_type, unit, status, created_at, updated_at
)
SELECT
  ${sqlString(channelRefId)}, candidate.organization_id, candidate.climate_chamber_id,
  candidate.bus_id, candidate.device_id, ${sqlString(channelId)},
  ${sqlString(sourceChannelId)}, candidate.channel_number, candidate.logical_sensor_number,
  'Acceptance channel without sample', 1, candidate.metric_type, candidate.unit,
  'active', NOW(), NOW()
FROM candidate;

SELECT COUNT(*) FROM measurement_channels WHERE id = ${sqlString(channelRefId)};
`);
  if (!output.trim().endsWith("1")) throw new Error("No-sample canonical channel was not seeded");
  return channelId;
}

function seedPersistedDashboard(): { dashboardId: string; dashboardName: string } {
  const dashboardId = randomUUID();
  const itemId = randomUUID();
  const dashboardName = `КК1 read-only ${Date.now()}`;
  const output = postgres(`
INSERT INTO live_dashboards (
  id, organization_id, name, description, owner_subject, refresh_seconds, time_window,
  version, status, created_by, updated_by, created_at, updated_at
)
VALUES (
  ${sqlString(dashboardId)}, ${sqlString(organizationId)}, ${sqlString(dashboardName)},
  'Persisted browser acceptance', 'acceptance-fixture', 2, '1h', 1, 'active',
  'acceptance-fixture', 'acceptance-fixture', NOW(), NOW()
);

INSERT INTO live_dashboard_items (
  id, organization_id, dashboard_id, position, channel_ref_id, channel_id, metric,
  native_unit, visualization, color, display_unit
)
SELECT
  ${sqlString(itemId)}, ${sqlString(organizationId)}, ${sqlString(dashboardId)}, 1,
  channel.id, channel.channel_id, channel.metric_type, channel.unit, 'area', '#00C6E0', channel.unit
FROM measurement_channels AS channel
WHERE channel.organization_id = ${sqlString(organizationId)}
  AND channel.channel_id = '106-03'
  AND channel.metric_type = 'temperature.probe'
  AND channel.status = 'active'
LIMIT 1;

SELECT COUNT(*) FROM live_dashboard_items WHERE dashboard_id = ${sqlString(dashboardId)};
`);
  if (!output.trim().endsWith("1")) throw new Error("Canonical 106-03 dashboard item was not seeded");
  return { dashboardId, dashboardName };
}

function seedChartSystemDashboard(): {
  dashboardId: string;
  dashboardName: string;
  plottedChannels: string[];
} {
  const dashboardId = randomUUID();
  const dashboardName = `Chart System ${Date.now()}`;
  const itemIds = [randomUUID(), randomUUID(), randomUUID(), randomUUID()];
  const output = postgres(`
INSERT INTO live_dashboards (
  id, organization_id, name, description, owner_subject, refresh_seconds, time_window,
  version, status, created_by, updated_by, created_at, updated_at
)
VALUES (
  ${sqlString(dashboardId)}, ${sqlString(organizationId)}, ${sqlString(dashboardName)},
  'Issue 404 canonical renderer acceptance', 'acceptance-fixture', 2, '1h', 1, 'active',
  'acceptance-fixture', 'acceptance-fixture', NOW(), NOW()
);

WITH group_choice AS (
  SELECT metric_type, unit
  FROM measurement_channels
  WHERE organization_id = ${sqlString(organizationId)}
    AND status = 'active'
  GROUP BY metric_type, unit
  HAVING COUNT(*) >= 4
  ORDER BY CASE WHEN metric_type = 'temperature.probe' THEN 0 ELSE 1 END, metric_type, unit
  LIMIT 1
),
ranked AS (
  SELECT
    channel.id,
    channel.channel_id,
    channel.metric_type,
    channel.unit,
    ROW_NUMBER() OVER (ORDER BY channel.channel_id, channel.id) AS position
  FROM measurement_channels AS channel
  JOIN group_choice
    ON group_choice.metric_type = channel.metric_type
   AND group_choice.unit = channel.unit
  WHERE channel.organization_id = ${sqlString(organizationId)}
    AND channel.status = 'active'
)
INSERT INTO live_dashboard_items (
  id, organization_id, dashboard_id, position, channel_ref_id, channel_id, metric,
  native_unit, visualization, color, display_unit
)
SELECT
  CASE ranked.position
    WHEN 1 THEN ${sqlString(itemIds[0])}
    WHEN 2 THEN ${sqlString(itemIds[1])}
    WHEN 3 THEN ${sqlString(itemIds[2])}
    ELSE ${sqlString(itemIds[3])}
  END,
  ${sqlString(organizationId)},
  ${sqlString(dashboardId)},
  ranked.position,
  ranked.id,
  ranked.channel_id,
  ranked.metric_type,
  ranked.unit,
  CASE ranked.position WHEN 1 THEN 'line' WHEN 2 THEN 'area' WHEN 3 THEN 'value' ELSE 'gauge' END,
  CASE ranked.position WHEN 1 THEN '#00C6E0' WHEN 2 THEN '#7ED321' WHEN 3 THEN '#0077FF' ELSE '#A855F7' END,
  ranked.unit
FROM ranked
WHERE ranked.position <= 4;

INSERT INTO telemetry_samples (
  event_id, node_id, captured_at, metric, value, unit, quality, source,
  equipment_id, channel_id, alarm, raw_value, raw_status, raw_payload
)
SELECT
  md5(item.id || ':' || sample_index::text),
  'edge-chart-404',
  NOW() - ((5 - sample_index) * INTERVAL '5 minutes'),
  item.metric,
  (item.position * 10 + sample_index)::double precision,
  item.native_unit,
  'valid',
  'issue-404-e2e',
  'saved-dashboard-e2e',
  item.channel_id,
  CASE WHEN item.position = 1 AND sample_index = 3 THEN 'high' ELSE NULL END,
  item.position * 100 + sample_index,
  NULL,
  '{}'::json
FROM live_dashboard_items AS item
CROSS JOIN generate_series(1, 4) AS sample_index
WHERE item.dashboard_id = ${sqlString(dashboardId)};

INSERT INTO telemetry_latest (
  sample_id, event_id, node_id, captured_at, metric, value, unit, quality, source,
  equipment_id, channel_id, alarm, raw_value, raw_status, stale_after_seconds, received_at
)
SELECT DISTINCT ON (sample.channel_id, sample.metric)
  sample.id, sample.event_id, sample.node_id, sample.captured_at, sample.metric, sample.value,
  sample.unit, sample.quality, sample.source, sample.equipment_id, sample.channel_id, sample.alarm,
  sample.raw_value, sample.raw_status, NULL, sample.received_at
FROM telemetry_samples AS sample
JOIN live_dashboard_items AS item
  ON item.dashboard_id = ${sqlString(dashboardId)}
 AND item.channel_id = sample.channel_id
 AND item.metric = sample.metric
WHERE sample.node_id = 'edge-chart-404'
  AND sample.equipment_id = 'saved-dashboard-e2e'
ORDER BY sample.channel_id, sample.metric, sample.captured_at DESC, sample.id DESC;

SELECT
  COUNT(*)::text || '|' ||
  COALESCE(string_agg(channel_id, ',' ORDER BY position) FILTER (WHERE position <= 2), '')
FROM live_dashboard_items
WHERE dashboard_id = ${sqlString(dashboardId)};
`);
  const summary = output.trim().split(/\n/).at(-1)?.trim() ?? "";
  const [count, channels = ""] = summary.split("|");
  if (count !== "4") throw new Error(`Chart System dashboard seeded ${count || "0"} items instead of 4`);
  const plottedChannels = channels.split(",").filter(Boolean);
  if (plottedChannels.length !== 2)
    throw new Error("Chart System dashboard did not seed two plotted channels");
  return { dashboardId, dashboardName, plottedChannels };
}

function persistTemperature(value: number, minutesAgo: number): void {
  const eventId = randomUUID();
  const capturedAt = new Date(Date.now() - minutesAgo * 60_000).toISOString();
  postgres(`
INSERT INTO telemetry_samples (
  event_id, node_id, captured_at, metric, value, unit, quality, source,
  equipment_id, channel_id, alarm, raw_value, raw_status, raw_payload
)
VALUES (
  ${sqlString(eventId)}, 'edge-live-01', ${sqlString(capturedAt)}::timestamptz,
  'temperature.probe', ${value}, 'degC', 'valid', 'dixell-xjp60d',
  'K106', '106-03', NULL, ${Math.round(value * 10)}, 4354, '{}'::json
);
`);
}

function observeRequests(page: Page): {
  dashboard: ObservedRequest[];
  telemetry: ObservedRequest[];
  acquisitionMutations: ObservedRequest[];
} {
  const dashboard: ObservedRequest[] = [];
  const telemetry: ObservedRequest[] = [];
  const acquisitionMutations: ObservedRequest[] = [];
  page.on("request", (request) => {
    const observed = { url: request.url(), method: request.method() };
    const pathname = new URL(observed.url).pathname.toLowerCase();
    if (pathname.includes("/api/v1/live-dashboards")) dashboard.push(observed);
    if (pathname.includes("/api/v1/telemetry/")) telemetry.push(observed);
    const mutating = !["GET", "HEAD", "OPTIONS"].includes(observed.method);
    const acquisitionPath =
      pathname.includes("device-agent") ||
      pathname.includes("/discovery") ||
      pathname.includes("/configuration") ||
      pathname.includes("/config/");
    if (mutating && acquisitionPath) acquisitionMutations.push(observed);
  });
  return { dashboard, telemetry, acquisitionMutations };
}

function observePublicRuntimeRequests(page: Page): ObservedRequest[] {
  const publicRequests: ObservedRequest[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!url.protocol.startsWith("http")) return;
    const host = url.hostname;
    const local =
      host === "localhost" ||
      host === "127.0.0.1" ||
      host === "::1" ||
      host.startsWith("10.") ||
      host.startsWith("192.168.") ||
      /^172\.(1[6-9]|2\d|3[01])\./.test(host);
    if (!local) publicRequests.push({ url: request.url(), method: request.method() });
  });
  return publicRequests;
}

function observeSockets(page: Page): SocketEvidence {
  const evidence: SocketEvidence = { opened: 0, closed: 0, active: 0, maximum: 0 };
  page.on("websocket", (socket) => {
    evidence.opened += 1;
    evidence.active += 1;
    evidence.maximum = Math.max(evidence.maximum, evidence.active);
    socket.on("close", () => {
      evidence.closed += 1;
      evidence.active = Math.max(0, evidence.active - 1);
    });
  });
  return evidence;
}

async function waitForApiReady(): Promise<void> {
  await expect
    .poll(
      async () => {
        try {
          return (await fetch(`${apiBaseUrl}/health/ready`)).ok;
        } catch {
          return false;
        }
      },
      { timeout: 60_000 },
    )
    .toBe(true);
}

test("editor loads the canonical catalog and selects a channel without telemetry history", async ({
  browser,
}) => {
  mkdirSync(evidenceDirectory, { recursive: true });
  const noSampleChannelId = seedNoSampleChannel();
  const context = await authenticatedContext(browser);
  const page = await context.newPage();
  const requests = observeRequests(page);

  await page.route("**/api/v1/auth/session", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        authenticated: true,
        identity: {
          id: "acceptance-editor-identity",
          provider: "acceptance-oidc",
          subject: "viewer-acceptance",
          email: "viewer@example.test",
          display_name: "Editor Acceptance",
        },
        memberships: [
          {
            organization_id: organizationId,
            organization_slug: "dashboard-acceptance",
            organization_name: "NEXOLAB Dashboard Acceptance",
            roles: ["operator"],
            permissions: [
              "dashboard.read",
              "live_dashboards.manage",
              "telemetry.read",
              "alerts.read",
              "reports.read",
              "nodes.read",
            ],
          },
        ],
      }),
    });
  });

  try {
    await page.goto("/live", { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: "Створити Dashboard" }).click();
    await expect(page.getByRole("heading", { name: "Новий Live Dashboard", exact: true })).toBeVisible();
    await expect
      .poll(() => requests.dashboard.some((item) => item.url.includes("/channel-inventory")))
      .toBe(true);

    const catalogCard = page.locator("article").filter({ hasText: noSampleChannelId });
    await expect(catalogCard).toContainText("Якість: Невідомі");
    await expect(catalogCard).toContainText("Тривога: немає");
    await catalogCard.getByRole("button", { name: "Додати", exact: true }).click();
    await expect(page.getByText("1 / 64 вибрано", { exact: true })).toBeVisible();
    await expect(page.getByText(`${noSampleChannelId} додано.`, { exact: true })).toBeVisible();

    expect(requests.telemetry).toEqual([]);
    expect(requests.acquisitionMutations).toEqual([]);
    expect(
      requests.dashboard
        .filter((item) => item.url.includes("/channel-inventory"))
        .every((item) => item.method === "GET"),
    ).toBe(true);

    await page.screenshot({
      path: path.join(evidenceDirectory, "live-dashboard-no-sample-editor.png"),
      fullPage: true,
    });
    writeFileSync(
      path.join(evidenceDirectory, "live-dashboard-inventory-summary.json"),
      `${JSON.stringify(
        {
          noSampleChannelId,
          dashboardRequests: requests.dashboard,
          telemetryRequests: requests.telemetry,
          acquisitionMutations: requests.acquisitionMutations,
        },
        null,
        2,
      )}\n`,
    );
  } finally {
    await context.close();
  }
});

test("opens a persisted selected-series dashboard after service restart without write controls", async ({
  browser,
}) => {
  mkdirSync(evidenceDirectory, { recursive: true });
  persistTemperature(3.8, 40);
  persistTemperature(4.1, 15);
  persistTemperature(4.4, 1);
  const fixture = seedPersistedDashboard();

  const context = await authenticatedContext(browser);
  const page = await context.newPage();
  const requests = observeRequests(page);
  const sockets = observeSockets(page);

  try {
    await page.goto("/live", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Live Dashboards", exact: true })).toBeVisible();
    await expect(page.getByText(fixture.dashboardName, { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Створити Dashboard" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Редагувати/ })).toHaveCount(0);

    const telemetryBeforeOpen = requests.telemetry.length;
    await page
      .locator("article")
      .filter({ hasText: fixture.dashboardName })
      .getByRole("button", { name: "Відкрити" })
      .click();
    await expect(page.getByRole("heading", { name: fixture.dashboardName, exact: true })).toBeVisible();
    const selectedChannelRow = page
      .getByRole("row")
      .filter({ has: page.getByRole("cell", { name: "106-03", exact: true }) });
    await expect(selectedChannelRow).toBeVisible();
    await expect(selectedChannelRow).toContainText(/-?\d+(?:[,.]\d+)? degC/);
    await expect.poll(() => sockets.maximum).toBe(1);

    await expect
      .poll(() => requests.telemetry.slice(telemetryBeforeOpen).some((item) => item.url.includes("/latest")))
      .toBe(true);
    await expect
      .poll(() => requests.telemetry.slice(telemetryBeforeOpen).some((item) => item.url.includes("/history")))
      .toBe(true);
    const selectedRequests = requests.telemetry.slice(telemetryBeforeOpen);
    expect(
      selectedRequests
        .filter((item) => item.url.includes("/latest") || item.url.includes("/history"))
        .every((item) => {
          const url = new URL(item.url);
          return (
            url.searchParams.get("channel_id") === "106-03" &&
            url.searchParams.get("metric") === "temperature.probe"
          );
        }),
    ).toBe(true);
    expect(requests.acquisitionMutations).toEqual([]);

    await page.getByRole("button", { name: "До library" }).click();
    compose(["restart", "telemetry-service"]);
    await waitForApiReady();
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.getByText(fixture.dashboardName, { exact: true })).toBeVisible();

    await page.screenshot({
      path: path.join(evidenceDirectory, "live-dashboard-persisted-library.png"),
      fullPage: true,
    });
    writeFileSync(
      path.join(evidenceDirectory, "live-dashboard-summary.json"),
      `${JSON.stringify(
        {
          dashboardId: fixture.dashboardId,
          dashboardName: fixture.dashboardName,
          dashboardRequests: requests.dashboard,
          selectedTelemetryRequests: selectedRequests,
          websocket: sockets,
          acquisitionMutations: requests.acquisitionMutations,
        },
        null,
        2,
      )}\n`,
    );
  } finally {
    await context.close();
  }
});

test("persisted Saved Dashboard uses canonical charts without renderer leaks or runtime mutation", async ({
  browser,
}) => {
  mkdirSync(evidenceDirectory, { recursive: true });
  const fixture = seedChartSystemDashboard();
  const context = await authenticatedContext(browser);
  const page = await context.newPage();
  const requests = observeRequests(page);
  const sockets = observeSockets(page);
  const publicRequests = observePublicRuntimeRequests(page);

  try {
    await page.goto("/live", { waitUntil: "domcontentloaded" });
    await expect(page.getByText(fixture.dashboardName, { exact: true })).toBeVisible();
    await page
      .locator("article")
      .filter({ hasText: fixture.dashboardName })
      .getByRole("button", { name: "Відкрити" })
      .click();
    await expect(page.getByRole("heading", { name: fixture.dashboardName, exact: true })).toBeVisible();

    const panel = page.getByTestId("saved-dashboard-chart-panel");
    await expect(panel).toHaveCount(1);
    await expect(panel.getByTestId("chart-renderer-host")).toBeVisible();
    await expect(panel.getByTestId("chart-accessible-summary")).toContainText("2 series");
    await expect.poll(() => panel.locator("canvas").count()).toBeGreaterThan(0);
    await expect(panel.locator("svg")).toHaveCount(0);
    for (const channelId of fixture.plottedChannels) await expect(panel).toContainText(channelId);
    await expect(page.getByTestId("saved-dashboard-value-card")).toHaveCount(1);
    await expect(page.getByTestId("saved-dashboard-gauge-card")).toHaveCount(1);
    await expect(page.getByTestId("saved-dashboard-value-card")).not.toContainText("—");
    await expect(page.getByTestId("saved-dashboard-gauge-card")).not.toContainText("—");
    await expect
      .poll(() => requests.telemetry.filter((item) => item.url.includes("/history")).length)
      .toBeGreaterThanOrEqual(4);

    const historyRequestsBeforeInteraction = requests.telemetry.filter((item) =>
      item.url.includes("/history"),
    ).length;
    const hostBeforeLivePoint = panel.getByTestId("chart-renderer-host");
    await hostBeforeLivePoint.evaluate((element) => {
      element.setAttribute("data-continuity-token", "issue-404-stable-host");
    });
    const canvasBeforeLivePoint = panel.locator("canvas").first();
    await canvasBeforeLivePoint.evaluate((element) => {
      element.setAttribute("data-canvas-continuity-token", "issue-404-stable-canvas");
    });
    publishSavedDashboardSample(fixture.dashboardId, fixture.plottedChannels[0], 19.75);
    await page.waitForTimeout(2_500);
    await expect(panel).toHaveCount(1);
    await expect(hostBeforeLivePoint).toBeVisible();
    await expect(hostBeforeLivePoint).toHaveAttribute("data-continuity-token", "issue-404-stable-host");
    await expect(canvasBeforeLivePoint).toHaveAttribute(
      "data-canvas-continuity-token",
      "issue-404-stable-canvas",
    );
    await expect.poll(() => panel.locator("canvas").count()).toBeGreaterThan(0);
    expect(requests.telemetry.filter((item) => item.url.includes("/history")).length).toBe(
      historyRequestsBeforeInteraction,
    );

    const dashboardMutationsBeforeInteraction = requests.dashboard.filter(
      (item) => !["GET", "HEAD", "OPTIONS"].includes(item.method),
    ).length;

    await panel.getByRole("button", { name: "Hide" }).first().click();
    await expect(panel.getByRole("button", { name: "Show" })).toHaveCount(1);
    await panel.getByRole("button", { name: "Solo" }).first().click();

    const host = panel.getByTestId("chart-renderer-host");
    const box = await host.boundingBox();
    if (!box) throw new Error("Saved Dashboard chart host has no bounding box");
    await host.hover();
    await page.mouse.wheel(0, -500);
    await page.mouse.move(box.x + box.width * 0.7, box.y + box.height * 0.5);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * 0.45, box.y + box.height * 0.5, { steps: 5 });
    await page.mouse.up();
    await panel.getByRole("button", { name: "Reset zoom" }).click();
    await expect(host).toBeVisible();

    for (const width of [360, 1440, 1920]) {
      await page.setViewportSize({ width, height: 900 });
      await expect(host).toBeVisible();
      await expect
        .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
        .toBe(true);
    }

    expect(
      requests.dashboard.filter((item) => !["GET", "HEAD", "OPTIONS"].includes(item.method)).length,
    ).toBe(dashboardMutationsBeforeInteraction);
    expect(requests.acquisitionMutations).toEqual([]);
    expect(publicRequests).toEqual([]);
    expect(requests.telemetry.filter((item) => item.url.includes("/history")).length).toBe(
      historyRequestsBeforeInteraction,
    );

    const maximumSocketsAfterOpen = sockets.maximum;
    expect(maximumSocketsAfterOpen).toBeGreaterThan(0);
    expect(maximumSocketsAfterOpen).toBeLessThanOrEqual(4);
    await page.getByRole("button", { name: "До library" }).click();
    await expect(panel).toHaveCount(0);
    await expect.poll(() => sockets.active).toBe(0);

    await page
      .locator("article")
      .filter({ hasText: fixture.dashboardName })
      .getByRole("button", { name: "Відкрити" })
      .click();
    await expect(page.getByTestId("saved-dashboard-chart-panel")).toHaveCount(1);
    await expect.poll(() => sockets.active).toBeGreaterThan(0);
    expect(sockets.maximum).toBeLessThanOrEqual(maximumSocketsAfterOpen);

    await page.screenshot({
      path: path.join(evidenceDirectory, "saved-dashboard-chart-system.png"),
      fullPage: true,
    });
    writeFileSync(
      path.join(evidenceDirectory, "saved-dashboard-chart-system-summary.json"),
      `${JSON.stringify(
        {
          dashboardId: fixture.dashboardId,
          dashboardName: fixture.dashboardName,
          plottedChannels: fixture.plottedChannels,
          websocket: sockets,
          publicRequests,
          acquisitionMutations: requests.acquisitionMutations,
          dashboardRequests: requests.dashboard,
          telemetryRequests: requests.telemetry,
        },
        null,
        2,
      )}\n`,
    );
  } finally {
    await context.close();
  }
});

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for Live Dashboard acceptance`);
  return value;
}
