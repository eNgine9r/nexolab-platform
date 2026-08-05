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

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for Live Dashboard acceptance`);
  return value;
}
