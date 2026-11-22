import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Browser, type BrowserContext, type Locator, type Page } from "@playwright/test";

import { toZonedInputValue } from "../src/features/display-time/zoned-input";

// Issue #1688: real-stack acceptance of the unified "Власний період" (#1683) on the Overview
// temperature history and the Energy comparison history. Every fixture lives in its own
// deterministic window several days in the past and is removed again after the test.

const organizationId = requiredEnvironment("NEXOLAB_DASHBOARD_ORGANIZATION_ID");
const viewerToken = requiredEnvironment("NEXOLAB_DASHBOARD_VIEWER_TOKEN");
const evidenceDirectory = process.env.NEXOLAB_DASHBOARD_EVIDENCE_DIR ?? "dashboard-acceptance-evidence";
const composeProject = requiredEnvironment("COMPOSE_PROJECT_NAME");
const baseCompose = requiredEnvironment("NEXOLAB_DASHBOARD_BASE_COMPOSE");
const acceptanceCompose = requiredEnvironment("NEXOLAB_DASHBOARD_ACCEPTANCE_COMPOSE");
const postgresUser = process.env.POSTGRES_USER?.trim() || "nexolab";
const postgresDatabase = process.env.POSTGRES_DB?.trim() || "nexolab";
const mqttTopic = process.env.MQTT_TOPIC ?? "nexolab/telemetry";

const DISPLAY_TIME_ZONE = "Europe/Kyiv";
const MINUTE_MS = 60_000;
const DAY_MS = 24 * 60 * MINUTE_MS;
const PRESET_LABELS = ["1 година", "6 годин", "24 години", "7 днів", "Власний період"] as const;
const FIXED_NOTICE = "Фіксований період: нові вимірювання не додаються";
const FIXTURE_SOURCE = "custom-range-acceptance-1688";

type TelemetryPoint = {
  nodeId: string;
  equipmentId: string;
  channelId: string;
  metric: string;
  unit: string;
  source: string;
  rawStatus: number | null;
};

type HistoryRequest = { url: string; from: string | null; to: string | null; params: Record<string, string> };

type InvalidCase = { name: string; fromMs: number; toMs: number; message: string };

const overviewPoint: TelemetryPoint = {
  nodeId: "edge-live-01",
  equipmentId: "K106",
  channelId: "106-03",
  metric: "temperature.probe",
  unit: "degC",
  source: "dixell-xjp60d",
  rawStatus: 4354,
};

const energyPoint: TelemetryPoint = {
  nodeId: "edge-01",
  equipmentId: "LE01MP-200",
  channelId: "200-active-power",
  metric: "electrical.power.active",
  unit: "W",
  source: "f-and-f-le-01mp",
  rawStatus: null,
};

async function kyivContext(browser: Browser): Promise<BrowserContext> {
  const context = await browser.newContext({
    timezoneId: DISPLAY_TIME_ZONE,
    viewport: { width: 1440, height: 1000 },
  });
  await context.addInitScript(
    ({ accessToken, organization }) => {
      if (window.location.protocol === "about:") return;
      window.sessionStorage.setItem("nexolab.acceptance.access-token", accessToken);
      window.sessionStorage.setItem("nexolab.acceptance.organization-id", organization);
    },
    { accessToken: viewerToken, organization: organizationId },
  );
  return context;
}

function composeExec(args: string[]): string {
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
  return composeExec([
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

function minuteFloor(timestampMs: number): number {
  return Math.floor(timestampMs / MINUTE_MS) * MINUTE_MS;
}

function kyivInput(timestampMs: number): string {
  return toZonedInputValue(timestampMs, DISPLAY_TIME_ZONE);
}

/** Inserts retained history rows directly; they are older than every latest projection row. */
function seedHistory(
  point: TelemetryPoint,
  rows: Array<{ eventId: string; capturedAtMs: number; value: number }>,
) {
  const values = rows
    .map(
      (row) => `(
  ${sqlString(row.eventId)}, ${sqlString(point.nodeId)}, ${sqlString(new Date(row.capturedAtMs).toISOString())}::timestamptz,
  ${sqlString(point.metric)}, ${row.value}, ${sqlString(point.unit)}, 'valid', ${sqlString(FIXTURE_SOURCE)},
  ${sqlString(point.equipmentId)}, ${sqlString(point.channelId)}, NULL, ${Math.round(row.value * 10)},
  ${point.rawStatus === null ? "NULL" : point.rawStatus}, '{}'::json
)`,
    )
    .join(",\n");
  const output = postgres(`
INSERT INTO telemetry_samples (
  event_id, node_id, captured_at, metric, value, unit, quality, source,
  equipment_id, channel_id, alarm, raw_value, raw_status, raw_payload
)
VALUES ${values};
SELECT COUNT(*) FROM telemetry_samples WHERE event_id IN (${rows.map((row) => sqlString(row.eventId)).join(", ")});
`);
  if (output.trim().split(/\n/).at(-1)?.trim() !== String(rows.length)) {
    throw new Error(`Custom-range history fixture for ${point.channelId} was not seeded`);
  }
}

/** Publishes a real live sample through MQTT so it is persisted and pushed over the WebSocket. */
function publishLiveSample(point: TelemetryPoint, eventId: string, value: number): void {
  const payload = JSON.stringify({
    event_id: eventId,
    node_id: point.nodeId,
    captured_at: new Date().toISOString(),
    metric: point.metric,
    value,
    unit: point.unit,
    quality: "valid",
    source: point.source,
    equipment_id: point.equipmentId,
    channel_id: point.channelId,
    alarm: null,
    raw_value: Math.round(value * 10),
    raw_status: point.rawStatus,
  });
  composeExec(["exec", "-T", "mqtt", "mosquitto_pub", "-h", "127.0.0.1", "-t", mqttTopic, "-m", payload]);
}

/**
 * Removes every fixture row created by a test. A live sample may have become the latest projection
 * row, so that row is first rewound to the newest remaining sample (or dropped when none remains),
 * exactly as the projection would look had the fixture never been ingested.
 */
async function removeFixtureRows(
  eventIds: readonly string[],
  liveEventIds: readonly string[],
): Promise<void> {
  if (eventIds.length === 0) return;
  const list = eventIds.map(sqlString).join(", ");
  // A published sample is persisted asynchronously; wait for it so it cannot land after cleanup.
  if (liveEventIds.length > 0) {
    const liveList = liveEventIds.map(sqlString).join(", ");
    for (let attempt = 0; attempt < 40; attempt += 1) {
      const count = postgres(
        `SELECT COUNT(*) FROM telemetry_samples WHERE event_id IN (${liveList});`,
      ).trim();
      if (count === String(liveEventIds.length)) break;
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  }
  postgres(`
BEGIN;
WITH removed AS (
  SELECT DISTINCT node_id, equipment_id, channel_id, metric
  FROM telemetry_samples
  WHERE event_id IN (${list})
),
best AS (
  SELECT DISTINCT ON (sample.node_id, sample.equipment_id, sample.channel_id, sample.metric) sample.*
  FROM telemetry_samples AS sample
  JOIN removed USING (node_id, equipment_id, channel_id, metric)
  WHERE sample.event_id NOT IN (${list})
  ORDER BY sample.node_id, sample.equipment_id, sample.channel_id, sample.metric,
    sample.captured_at DESC, sample.id DESC
)
UPDATE telemetry_latest AS latest
SET sample_id = best.id, event_id = best.event_id, captured_at = best.captured_at, value = best.value,
  unit = best.unit, quality = best.quality, source = best.source, alarm = best.alarm,
  raw_value = best.raw_value, raw_status = best.raw_status, received_at = best.received_at
FROM best
WHERE latest.event_id IN (${list})
  AND latest.node_id = best.node_id
  AND latest.equipment_id = best.equipment_id
  AND latest.channel_id = best.channel_id
  AND latest.metric = best.metric;
DELETE FROM telemetry_latest WHERE event_id IN (${list});
DELETE FROM telemetry_samples WHERE event_id IN (${list});
COMMIT;
`);
}

function observeHistoryRequests(page: Page, nodeId?: string): HistoryRequest[] {
  const requests: HistoryRequest[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!url.pathname.endsWith("/api/v1/telemetry/history")) return;
    if (nodeId && url.searchParams.get("node_id") !== nodeId) return;
    requests.push({
      url: request.url(),
      from: url.searchParams.get("from"),
      to: url.searchParams.get("to"),
      params: Object.fromEntries(url.searchParams.entries()),
    });
  });
  return requests;
}

function invalidCases(fixedFromMs: number, fixedToMs: number): InvalidCase[] {
  const now = minuteFloor(Date.now());
  return [
    {
      name: "start after end",
      fromMs: fixedToMs,
      toMs: fixedFromMs,
      message: "Початок діапазону має бути раніше завершення.",
    },
    {
      name: "longer than 31 days",
      fromMs: now - 40 * DAY_MS,
      toMs: now - DAY_MS,
      message: "Діапазон не може перевищувати 31 день.",
    },
    {
      name: "start in the future",
      fromMs: now + 2 * 60 * MINUTE_MS,
      toMs: now + 3 * 60 * MINUTE_MS,
      message: "Початок періоду має бути в минулому.",
    },
  ];
}

async function expectFivePresets(group: Locator): Promise<void> {
  for (const label of PRESET_LABELS) {
    await expect(group.getByRole("button", { name: label, exact: true })).toBeVisible();
  }
  await expect(group.getByRole("button", { name: "30 днів", exact: true })).toHaveCount(0);
}

async function fillCustomRange(form: Locator, fromMs: number, toMs: number): Promise<void> {
  await form.getByLabel("Від", { exact: true }).fill(kyivInput(fromMs));
  await form.getByLabel("До", { exact: true }).fill(kyivInput(toMs));
  await form.getByRole("button", { name: "Застосувати", exact: true }).click();
}

/**
 * Every invalid period is rejected in Ukrainian, the form stays open, the previously selected
 * preset stays selected and no history request is issued.
 */
async function expectInvalidPeriodsRejected(options: {
  group: Locator;
  form: Locator;
  notice: Locator;
  previousPreset: string;
  history: HistoryRequest[];
  cases: InvalidCase[];
}): Promise<void> {
  const { group, form, notice, previousPreset, history, cases } = options;
  const customButton = group.getByRole("button", { name: "Власний період", exact: true });
  const presetButton = group.getByRole("button", { name: previousPreset, exact: true });
  const requestsBefore = history.length;
  for (const item of cases) {
    await test.step(`reject ${item.name}`, async () => {
      await customButton.click();
      await expect(form).toBeVisible();
      await fillCustomRange(form, item.fromMs, item.toMs);
      await expect(form.getByRole("alert")).toHaveText(item.message);
      await expect(presetButton).toHaveAttribute("aria-pressed", "true");
      await expect(customButton).toHaveAttribute("aria-pressed", "false");
      await expect(notice).toHaveCount(0);
      await form.getByRole("button", { name: "Скасувати", exact: true }).click();
      await expect(form).toHaveCount(0);
      await expect(presetButton).toHaveAttribute("aria-pressed", "true");
    });
  }
  // Give a wrongly-applied period time to reach the network before asserting none was sent.
  await new Promise((resolve) => setTimeout(resolve, 500));
  expect(history.length).toBe(requestsBefore);
}

function expectExactWindow(requests: HistoryRequest[], fromIso: string, toIso: string): void {
  expect(requests.length).toBeGreaterThan(0);
  // The first page carries exactly the chosen bounds; later pages may only move `to` backwards.
  expect(requests[0].from).toBe(fromIso);
  expect(requests[0].to).toBe(toIso);
  for (const request of requests) {
    expect(request.from).toBe(fromIso);
    expect(Date.parse(request.to ?? "")).toBeLessThanOrEqual(Date.parse(toIso));
  }
}

test("Overview temperature history applies a fixed custom period against real PostgreSQL history", async ({
  browser,
}) => {
  mkdirSync(evidenceDirectory, { recursive: true });
  const anchorMs = minuteFloor(Date.now() - 4 * DAY_MS - 197 * MINUTE_MS);
  const fromMs = anchorMs - 30 * MINUTE_MS;
  const toMs = anchorMs + 30 * MINUTE_MS;
  const fromIso = new Date(fromMs).toISOString();
  const toIso = new Date(toMs).toISOString();
  const seeded = [-20, 0, 20].map((offset, index) => ({
    eventId: randomUUID(),
    capturedAtMs: anchorMs + offset * MINUTE_MS,
    value: 7.1 + index * 0.1,
  }));
  const liveEventId = randomUUID();
  const created = seeded.map((row) => row.eventId);
  const liveCreated: string[] = [];
  seedHistory(overviewPoint, seeded);

  const context = await kyivContext(browser);
  const page = await context.newPage();
  const history = observeHistoryRequests(page);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));

  try {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const section = page.getByTestId("overview-history-chart-system");
    await expect(section).toBeVisible();
    await expectFivePresets(section);
    await expect.poll(() => history.length).toBeGreaterThanOrEqual(1);

    const sixHours = section.getByRole("button", { name: "6 годин", exact: true });
    const customButton = section.getByRole("button", { name: "Власний період", exact: true });
    const requestsBeforeSixHours = history.length;
    await sixHours.click();
    await expect(sixHours).toHaveAttribute("aria-pressed", "true");
    await expect.poll(() => history.length).toBeGreaterThan(requestsBeforeSixHours);
    await expect(section.getByText("Завантаження історії…")).toHaveCount(0);

    const form = section.getByTestId("overview-custom-range-form");
    const notice = section.getByTestId("overview-custom-range-notice");
    await expectInvalidPeriodsRejected({
      group: section,
      form,
      notice,
      previousPreset: "6 годин",
      history,
      cases: invalidCases(fromMs, toMs),
    });

    const requestsBeforeCustom = history.length;
    const customResponse = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname.endsWith("/api/v1/telemetry/history") && url.searchParams.get("from") === fromIso;
    });
    await customButton.click();
    await expect(form.getByLabel("Від", { exact: true })).toBeVisible();
    await expect(form.getByLabel("До", { exact: true })).toBeVisible();
    await fillCustomRange(form, fromMs, toMs);
    await expect(form).toHaveCount(0);
    await expect(customButton).toHaveAttribute("aria-pressed", "true");
    await expect(sixHours).toHaveAttribute("aria-pressed", "false");
    await expect(notice).toContainText(FIXED_NOTICE);

    const response = await customResponse;
    expect(response.status()).toBe(200);
    const body = (await response.json()) as { items: Array<{ event_id: string }> };
    expect(body.items.map((item) => item.event_id).sort()).toEqual(created.slice().sort());

    await expect.poll(() => history.length).toBeGreaterThan(requestsBeforeCustom);
    const customRequests = history.slice(requestsBeforeCustom);
    expectExactWindow(customRequests, fromIso, toIso);
    expect(customRequests[0].params.metric).toBe("temperature.probe");

    await expect(section).toContainText("3 записів");
    const panel = section.getByTestId("overview-chart-panel");
    await expect(panel).toHaveCount(1);
    const host = panel.getByTestId("chart-renderer-host");
    await expect(host).toHaveAttribute("data-chart-x-domain-from-ms", String(fromMs));
    await expect(host).toHaveAttribute("data-chart-x-domain-to-ms", String(toMs));
    await expect.poll(() => panel.locator("canvas").count()).toBeGreaterThan(0);
    await expect(panel.getByTestId("chart-accessible-summary")).toContainText("Стан Фіксований період");
    await expect(panel).toContainText("106-03");
    await expect(panel).not.toContainText("Актуально");

    await test.step("a later live sample does not extend the fixed window", async () => {
      const noticeText = await notice.textContent();
      const requestsBeforeLive = history.length;
      liveCreated.push(liveEventId);
      created.push(liveEventId);
      publishLiveSample(overviewPoint, liveEventId, 6.4);
      // The live sample really reached the page: the current-value tile shows it.
      await expect(page.getByTestId("overview-live-value-grid")).toContainText(/6[,.]4 °C/);
      await page.waitForTimeout(1_500);
      await expect(section).toContainText("3 записів");
      await expect(host).toHaveAttribute("data-chart-x-domain-from-ms", String(fromMs));
      await expect(host).toHaveAttribute("data-chart-x-domain-to-ms", String(toMs));
      await expect(notice).toHaveText(noticeText ?? "");
      await expect(customButton).toHaveAttribute("aria-pressed", "true");
      await expect(panel).not.toContainText("Актуально");
      expect(history.length).toBe(requestsBeforeLive);
    });

    await page.screenshot({
      path: path.join(evidenceDirectory, "overview-custom-range.png"),
      fullPage: true,
    });
    writeFileSync(
      path.join(evidenceDirectory, "overview-custom-range-summary.json"),
      `${JSON.stringify({ fromIso, toIso, seeded: created, customRequests }, null, 2)}\n`,
    );
    expect(errors).toEqual([]);
  } finally {
    await context.close();
    await removeFixtureRows(created, liveCreated);
  }
});

test("Energy comparison history applies a fixed custom period against real PostgreSQL history", async ({
  browser,
}) => {
  mkdirSync(evidenceDirectory, { recursive: true });
  const anchorMs = minuteFloor(Date.now() - 5 * DAY_MS - 143 * MINUTE_MS);
  const fromMs = anchorMs - 30 * MINUTE_MS;
  const toMs = anchorMs + 30 * MINUTE_MS;
  const fromIso = new Date(fromMs).toISOString();
  const toIso = new Date(toMs).toISOString();
  const seeded = [-20, 0, 20].map((offset, index) => ({
    eventId: randomUUID(),
    capturedAtMs: anchorMs + offset * MINUTE_MS,
    value: 501 + index,
  }));
  const liveEventId = randomUUID();
  const created = seeded.map((row) => row.eventId);
  const liveCreated: string[] = [];
  seedHistory(energyPoint, seeded);

  const context = await kyivContext(browser);
  const page = await context.newPage();
  const history = observeHistoryRequests(page, energyPoint.nodeId);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));

  try {
    await page.goto("/energy", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Енергомоніторинг", exact: true })).toBeVisible();
    const chart = page.getByTestId("energy-history-chart");
    // Energy history may be empty for every preset (no other fixture yet): the chart host exists but
    // only renders a plot once the fixed period returns the seeded samples.
    await expect(chart).toHaveCount(1);
    const group = page.locator('[aria-label="Період історії"]');
    await expectFivePresets(group);
    await expect.poll(() => history.length).toBeGreaterThanOrEqual(1);

    const sixHours = group.getByRole("button", { name: "6 годин", exact: true });
    const customButton = group.getByRole("button", { name: "Власний період", exact: true });
    const requestsBeforeSixHours = history.length;
    await sixHours.click();
    await expect(sixHours).toHaveAttribute("aria-pressed", "true");
    await expect.poll(() => history.length).toBeGreaterThan(requestsBeforeSixHours);
    await expect(page.getByRole("status").filter({ hasText: "Завантаження історії…" })).toHaveCount(0);

    const form = page.getByTestId("energy-custom-range-form");
    const notice = page.getByTestId("energy-custom-range-notice");
    await expectInvalidPeriodsRejected({
      group,
      form,
      notice,
      previousPreset: "6 годин",
      history,
      cases: invalidCases(fromMs, toMs),
    });

    const requestsBeforeCustom = history.length;
    const customResponse = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return (
        url.pathname.endsWith("/api/v1/telemetry/history") &&
        url.searchParams.get("node_id") === energyPoint.nodeId &&
        url.searchParams.get("metric") === energyPoint.metric &&
        url.searchParams.get("from") === fromIso
      );
    });
    await customButton.click();
    await fillCustomRange(form, fromMs, toMs);
    await expect(form).toHaveCount(0);
    await expect(customButton).toHaveAttribute("aria-pressed", "true");
    await expect(sixHours).toHaveAttribute("aria-pressed", "false");
    await expect(notice).toContainText(FIXED_NOTICE);

    const response = await customResponse;
    expect(response.status()).toBe(200);
    const body = (await response.json()) as { items: Array<{ event_id: string }> };
    expect(body.items.map((item) => item.event_id).sort()).toEqual(created.slice().sort());

    await expect.poll(() => history.length).toBeGreaterThan(requestsBeforeCustom);
    const customRequests = history.slice(requestsBeforeCustom);
    expectExactWindow(
      customRequests.filter((request) => request.params.metric === energyPoint.metric),
      fromIso,
      toIso,
    );
    // Every selected metric of the fixed period is read for exactly the same window.
    for (const request of customRequests) {
      expect(request.from).toBe(fromIso);
      expect(Date.parse(request.to ?? "")).toBeLessThanOrEqual(Date.parse(toIso));
    }

    const host = chart.getByTestId("chart-renderer-host").first();
    await expect(host).toHaveAttribute("data-chart-x-domain-from-ms", String(fromMs));
    await expect(host).toHaveAttribute("data-chart-x-domain-to-ms", String(toMs));
    const summary = chart.getByTestId("chart-accessible-summary").first();
    await expect(summary).toContainText("Стан Фіксований період");
    await expect(chart).not.toContainText("Актуально");
    const pointsText = page.getByText(/\d+ точок для відображення/);
    await expect(pointsText).not.toContainText(" 0 точок");
    const pointsBeforeLive = await pointsText.textContent();

    await test.step("a later live sample does not extend the fixed window", async () => {
      const noticeText = await notice.textContent();
      const requestsBeforeLive = history.length;
      liveCreated.push(liveEventId);
      created.push(liveEventId);
      publishLiveSample(energyPoint, liveEventId, 777);
      // The live sample really reached the page: the W1 meter card shows it.
      await expect(page.getByText("777 W", { exact: true }).first()).toBeVisible();
      await page.waitForTimeout(1_500);
      await expect(host).toHaveAttribute("data-chart-x-domain-from-ms", String(fromMs));
      await expect(host).toHaveAttribute("data-chart-x-domain-to-ms", String(toMs));
      await expect(pointsText).toHaveText(pointsBeforeLive ?? "");
      await expect(notice).toHaveText(noticeText ?? "");
      await expect(customButton).toHaveAttribute("aria-pressed", "true");
      await expect(chart).not.toContainText("Актуально");
      expect(history.length).toBe(requestsBeforeLive);
    });

    await page.screenshot({ path: path.join(evidenceDirectory, "energy-custom-range.png"), fullPage: true });
    writeFileSync(
      path.join(evidenceDirectory, "energy-custom-range-summary.json"),
      `${JSON.stringify({ fromIso, toIso, seeded: created, customRequests }, null, 2)}\n`,
    );
    expect(errors).toEqual([]);
  } finally {
    await context.close();
    await removeFixtureRows(created, liveCreated);
  }
});

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for custom-range acceptance`);
  return value;
}
