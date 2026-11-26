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
    await page.goto("/live", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Live дані", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Saved Dashboards" })).toBeVisible();

    const primaryChart = page.getByTestId("live-primary-chart");
    const filterPanel = page.getByTestId("live-filter-panel");
    const inventoryPanel = page.getByTestId("live-inventory-panel");
    await expect(primaryChart).toBeVisible();
    await expect(filterPanel).toBeVisible();
    await expect(inventoryPanel).toBeVisible();
    await expect(page.getByText("Живий потік підключено", { exact: true })).toBeVisible();

    const advancedFilters = filterPanel.getByRole("button", { name: /Додаткові фільтри/ });
    const nodeFilter = filterPanel.getByLabel("Вузол");
    await expect(advancedFilters).toHaveAttribute("aria-expanded", "false");
    await expect(nodeFilter).toBeHidden();
    const socketCountBeforeToggle = runtime.sockets.opened;
    const historyCountBeforeToggle = runtime.telemetry.filter((request) =>
      request.url.includes("/history"),
    ).length;
    await advancedFilters.focus();
    await page.keyboard.press("Enter");
    await expect(advancedFilters).toHaveAttribute("aria-expanded", "true");
    await expect(nodeFilter).toBeVisible();
    await advancedFilters.click();
    await expect(advancedFilters).toHaveAttribute("aria-expanded", "false");
    await expect(nodeFilter).toBeHidden();
    expect(runtime.sockets.opened).toBe(socketCountBeforeToggle);
    expect(runtime.telemetry.filter((request) => request.url.includes("/history")).length).toBe(
      historyCountBeforeToggle,
    );
    await expect(primaryChart.getByText("Жодного каналу не обрано", { exact: true })).toBeVisible();
    await primaryChart.getByRole("button", { name: "Обрати датчики" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("textbox", { name: "Пошук", exact: true })).toBeFocused();
    await expect(primaryChart.getByText("Оберіть датчики для графіка", { exact: true })).toBeVisible();
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

    const search = page.getByRole("textbox", { name: "Пошук", exact: true });
    await search.fill(fixture.equipmentId);
    const compare = page.getByRole("checkbox", { name: /Порівнювати/ });
    expect(
      await page.evaluate(() => {
        const chartButton = document.querySelector('[data-testid="live-primary-chart"] button');
        const searchInput = document.querySelector('[data-testid="live-filter-panel"] input');
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
    await expect(summary).toContainText("Період Live");
    await expect(summary).toContainText("Видимих серій 8");
    await expect(summary).toContainText("Осей 2");
    await expect(summary).toContainText("°C");
    await expect(summary).toContainText("V");
    await expect(summary).toContainText("Розривів безперервності 1");
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
    await expect(inspector).toContainText("Найближче виміряне значення для кожної видимої серії");
    await expect(inspector.getByRole("row")).toHaveCount(9);
    for (const channelId of fixture.channels) await expect(inspector).toContainText(channelId);
    await expect(inspector).toContainText(/\d+\.\d{2} °C/);
    await expect(inspector).toContainText(/\d+\.\d{2} V/);

    const inspectorTimestamp = inspector.locator("p").nth(1);
    const panProbe = {
      x: equipmentBox.x + equipmentBox.width * 0.72,
      y: equipmentBox.y + equipmentBox.height * 0.5,
    };
    const resumeProbeLeft = {
      x: equipmentBox.x + equipmentBox.width * 0.82,
      y: panProbe.y,
    };
    const resumeProbeRight = {
      x: equipmentBox.x + equipmentBox.width * 0.9,
      y: panProbe.y,
    };
    const readDomain = () =>
      equipmentHost.evaluate((host) => ({
        fromMs: Number(host.getAttribute("data-chart-x-domain-from-ms")),
        toMs: Number(host.getAttribute("data-chart-x-domain-to-ms")),
      }));
    await page.mouse.move(panProbe.x, panProbe.y);
    const initialInspectorTimestamp = (await inspectorTimestamp.textContent())?.trim();
    expect(initialInspectorTimestamp).toBeTruthy();
    const initialDomain = await readDomain();
    expect(initialDomain.toMs).toBeGreaterThan(initialDomain.fromMs);

    const historyRequestsBeforePan = runtime.telemetry.filter((request) =>
      request.url.includes("/history"),
    ).length;
    const acquisitionMutationsBeforePan = runtime.acquisitionMutations.length;
    const layoutBeforePan = await equipmentHost.evaluate((host) => {
      const bounds = host.getBoundingClientRect();
      const surface = host.querySelector('[data-testid="chart-renderer-surface"]');
      const canvas = surface?.querySelector("canvas") ?? null;
      Reflect.set(window, "__nexolabIssue415Refs", { host, surface, canvas });
      return { top: bounds.top, height: bounds.height, scrollY: window.scrollY };
    });

    await page.mouse.wheel(0, -600);
    await expect(page.getByText("Призупинений перегляд", { exact: true })).toBeVisible();
    await expect
      .poll(async () => {
        const domain = await readDomain();
        return domain.toMs - domain.fromMs;
      })
      .toBeLessThan(initialDomain.toMs - initialDomain.fromMs);
    const zoomedDomain = await readDomain();
    await page.mouse.move(panProbe.x, panProbe.y);
    const inspectorTimestampBeforePan = (await inspectorTimestamp.textContent())?.trim();
    expect(inspectorTimestampBeforePan).toBeTruthy();

    await page.mouse.down({ button: "left" });
    await page.mouse.move(equipmentBox.x + equipmentBox.width * 0.42, panProbe.y, { steps: 8 });
    await expect(inspectorTimestamp).toHaveText(inspectorTimestampBeforePan!);
    await page.mouse.up({ button: "left" });

    await expect
      .poll(async () => {
        const domain = await readDomain();
        return `${domain.fromMs}:${domain.toMs}`;
      })
      .not.toBe(`${zoomedDomain.fromMs}:${zoomedDomain.toMs}`);
    const pannedDomain = await readDomain();
    const zoomedSpan = zoomedDomain.toMs - zoomedDomain.fromMs;
    const pannedSpan = pannedDomain.toMs - pannedDomain.fromMs;
    expect(Math.abs(pannedSpan - zoomedSpan)).toBeLessThan(zoomedSpan * 0.02);

    await page.mouse.move(resumeProbeLeft.x, resumeProbeLeft.y);
    const resumedInspectorTimestamp = (await inspectorTimestamp.textContent())?.trim();
    expect(resumedInspectorTimestamp).toBeTruthy();
    await page.mouse.move(resumeProbeRight.x, resumeProbeRight.y);
    await expect
      .poll(async () => (await inspectorTimestamp.textContent())?.trim())
      .not.toBe(resumedInspectorTimestamp);

    await page.getByRole("button", { name: "Скинути масштаб" }).click();
    await expect.poll(readDomain).toEqual(initialDomain);
    await expect(page.getByText("Live-стеження", { exact: true })).toBeVisible();
    await page.mouse.move(panProbe.x, panProbe.y);
    await expect
      .poll(async () => (await inspectorTimestamp.textContent())?.trim())
      .toBe(initialInspectorTimestamp);

    const layoutAfterPan = await equipmentHost.evaluate((host) => {
      const bounds = host.getBoundingClientRect();
      const surface = host.querySelector('[data-testid="chart-renderer-surface"]');
      const canvas = surface?.querySelector("canvas") ?? null;
      const refs = Reflect.get(window, "__nexolabIssue415Refs") as
        { host: Element; surface: Element | null; canvas: Element | null } | undefined;
      return {
        top: bounds.top,
        height: bounds.height,
        scrollY: window.scrollY,
        sameHost: refs?.host === host,
        sameSurface: refs?.surface === surface,
        sameCanvas: refs?.canvas === canvas,
      };
    });
    expect(layoutAfterPan.sameHost).toBe(true);
    expect(layoutAfterPan.sameSurface).toBe(true);
    expect(layoutAfterPan.sameCanvas).toBe(true);
    expect(Math.abs(layoutAfterPan.top - layoutBeforePan.top)).toBeLessThan(1);
    expect(Math.abs(layoutAfterPan.height - layoutBeforePan.height)).toBeLessThan(1);
    expect(layoutAfterPan.scrollY).toBe(layoutBeforePan.scrollY);
    expect(runtime.telemetry.filter((request) => request.url.includes("/history"))).toHaveLength(
      historyRequestsBeforePan,
    );
    expect(runtime.acquisitionMutations).toHaveLength(acquisitionMutationsBeforePan);

    const historyRequestsBeforeLivePoint = runtime.telemetry.filter((request) =>
      request.url.includes("/history"),
    ).length;

    publishExplorerSample(fixture.equipmentId, fixture.channels[0], 9.876);
    await expect(page.getByText("9.88 °C", { exact: true }).first()).toBeVisible();
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
    // Every history request stays scoped to the selected fixture channels: raw pages by
    // channel_id, aggregated history (#1813) by its node|equipment|channel|metric series.
    expect(
      runtime.telemetry
        .filter((request) => request.url.includes("/history"))
        .every((request) => {
          const params = new URL(request.url).searchParams;
          const series = params.getAll("series");
          if (series.length > 0) {
            return series.every((key) => fixture.channels.includes(key.split("|")[2] ?? ""));
          }
          const channelId = params.get("channel_id");
          return channelId !== null && fixture.channels.includes(channelId);
        }),
    ).toBe(true);

    await page.getByRole("button", { name: "Приховати" }).first().click();
    await expect(page.getByRole("button", { name: "Показати" }).first()).toBeVisible();
    await expect(summary).toContainText("Видимих серій 7");
    await expect(summary).toContainText("Осей 2");
    await page.getByRole("button", { name: "Показати" }).first().click();
    await expect(summary).toContainText("Видимих серій 8");
    await page.getByRole("button", { name: "Лише цей" }).first().click();
    await expect(summary).toContainText("Видимих серій 1");
    await expect(summary).toContainText("Осей 1");
    await expect(inspector.getByRole("row")).toHaveCount(2);
    await expect(page.getByRole("button", { name: "Скинути масштаб" })).toHaveCount(1);

    await page.getByRole("button", { name: "5 min", exact: true }).click();
    await expect(summary).toContainText("Період 5 min");
    await page.getByRole("button", { name: "Повернутися до Live", exact: true }).click();
    await expect(page.getByText("Live-стеження", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Pause View", exact: true }).click();
    await expect(page.getByText("Призупинений перегляд", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Повернутися до Live", exact: true }).click();

    for (const viewport of [
      { width: 320, height: 800 },
      { width: 360, height: 800 },
      { width: 375, height: 800 },
      { width: 390, height: 800 },
      { width: 768, height: 900 },
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

for (const width of [390, 1280]) {
  test(`UTC/local updates the same measured sample, chart and retained route at ${width}px`, async ({
    browser,
  }) => {
    const fixture = seedExplorerTelemetry();
    const context = await authenticatedContext(browser, "Europe/Kyiv");
    const page = await context.newPage();
    await page.setViewportSize({ width, height: 1000 });
    const runtime = observeRuntime(page);
    try {
      await page.goto("/live", { waitUntil: "domcontentloaded" });
      await page.getByRole("textbox", { name: "Пошук", exact: true }).fill(fixture.equipmentId);
      await page
        .getByRole("checkbox", { name: /Порівнювати/ })
        .first()
        .check();
      const chart = page.getByTestId("live-primary-chart");
      const host = chart.getByTestId("chart-renderer-host");
      await expect(host).toBeVisible();
      await page.getByRole("button", { name: "Pause View", exact: true }).click();
      await host.focus();
      await page.keyboard.press("Home");
      const timestamp = chart.getByTestId("chart-inspector-timestamp");
      await expect(timestamp).toHaveAttribute("datetime", /T/);
      const instant = await timestamp.getAttribute("datetime");
      if (!instant) throw new Error("Inspector has no measured instant");
      const expected = (timeZone: string) =>
        new Intl.DateTimeFormat("uk-UA", {
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          timeZoneName: "short",
          timeZone,
        }).format(new Date(instant));
      await expect(timestamp).toHaveText(expected("Europe/Kyiv"));
      const beforeDomain = {
        from: await host.getAttribute("data-chart-x-domain-from-ms"),
        to: await host.getAttribute("data-chart-x-domain-to-ms"),
      };
      const beforeRows = await chart.getByTestId("chart-inspector").getByRole("row").count();
      const settings = await context.newPage();
      await settings.goto("/settings", { waitUntil: "domcontentloaded" });
      await settings.getByLabel("Часові позначки").selectOption("utc");
      await expect(timestamp).toHaveText(expected("UTC"));
      await expect(chart.getByTestId("chart-display-timezone")).toContainText("UTC");
      await expect(timestamp).toHaveAttribute("datetime", instant);
      await expect(host).toHaveAttribute("data-chart-x-domain-from-ms", beforeDomain.from!);
      await expect(host).toHaveAttribute("data-chart-x-domain-to-ms", beforeDomain.to!);
      await expect(chart.getByTestId("chart-inspector").getByRole("row")).toHaveCount(beforeRows);
      await settings.reload({ waitUntil: "domcontentloaded" });
      await expect(settings.getByLabel("Часові позначки")).toHaveValue("utc");
      await settings.getByLabel("Часові позначки").selectOption("local");
      await expect(timestamp).toHaveText(expected("Europe/Kyiv"));
      // Return to the same URL comparison context after its retained page suspends.
      const selectedUrl = page.url();
      await page.setViewportSize({ width: 1280, height: 1000 });
      await page.getByRole("link", { name: "Налаштування", exact: true }).click();
      await page.getByLabel("Часові позначки").selectOption("utc");
      await page.goBack({ waitUntil: "domcontentloaded" });
      await expect(page).toHaveURL(selectedUrl);
      await expect(chart.getByTestId("chart-display-timezone")).toContainText("UTC");
      await expect(page.getByRole("checkbox", { name: /Порівнювати/ }).first()).toBeChecked();
      await assertNoPageOverflow(page);
      expect(runtime.acquisitionMutations).toEqual([]);
    } finally {
      await context.close();
    }
  });
}

for (const width of [390, 1280]) {
  test(`Live comparison survives ordinary navigation and bare reload at ${width}px`, async ({ browser }) => {
    const fixture = seedExplorerTelemetry();
    const context = await authenticatedContext(browser);
    const page = await context.newPage();
    await page.setViewportSize({ width, height: 1000 });
    const runtime = observeRuntime(page);
    const preferenceKey = `nexolab.live-comparison.v1:${encodeURIComponent(organizationId)}`;
    const readPreference = () =>
      page.evaluate((key) => JSON.parse(localStorage.getItem(key) ?? "null"), preferenceKey);

    const navigate = async (name: string) => {
      if (width < 1024) await page.getByRole("button", { name: "Відкрити меню", exact: true }).click();
      const link = page.getByRole("navigation", { name: "Головна навігація" }).getByRole("link", {
        name,
        exact: true,
      });
      if (name === "Live дані") await expect(link).toHaveAttribute("href", "/live");
      await link.click();
    };

    try {
      await page.goto("/live", { waitUntil: "domcontentloaded" });
      await page.getByRole("textbox", { name: "Пошук", exact: true }).fill(fixture.equipmentId);
      await page
        .getByRole("checkbox", { name: /Порівнювати/ })
        .first()
        .check();
      await expect.poll(() => new URL(page.url()).searchParams.getAll("compare").length).toBe(1);
      const selected = new URL(page.url()).searchParams.getAll("compare");
      await expect.poll(readPreference).toEqual({ version: 1, keys: selected });

      await navigate("Налаштування");
      await expect(page.getByLabel("Часові позначки")).toBeVisible();
      await navigate("Live дані");
      const selectedContext = page.getByTestId("live-selected-context");
      await expect(selectedContext).toContainText(fixture.equipmentId);
      await expect.poll(() => new URL(page.url()).searchParams.getAll("compare")).toEqual(selected);
      await assertNoPageOverflow(page);

      await page.evaluate(() => window.history.replaceState(null, "", "/live"));
      await page.reload({ waitUntil: "domcontentloaded" });
      await expect(selectedContext).toContainText(fixture.equipmentId);
      await expect.poll(() => new URL(page.url()).searchParams.getAll("compare")).toEqual(selected);

      await page.getByRole("textbox", { name: "Пошук", exact: true }).fill(fixture.equipmentId);
      await page.getByRole("checkbox", { name: /Порівнювати/, checked: true }).uncheck();
      await expect.poll(readPreference).toEqual({ version: 1, keys: [] });
      await page.goto("/live", { waitUntil: "domcontentloaded" });
      await expect(page.getByText("Жодного каналу не обрано", { exact: true })).toBeVisible();
      await expect.poll(readPreference).toEqual({ version: 1, keys: [] });

      await page.goto(`/live?compare=${encodeURIComponent(selected[0]!)}&range=1h`);
      await expect(selectedContext).toContainText(fixture.equipmentId);
      await expect.poll(() => new URL(page.url()).searchParams.getAll("compare")).toEqual(selected);
      await assertNoPageOverflow(page);
      expect(runtime.acquisitionMutations).toEqual([]);
    } finally {
      await context.close();
    }
  });
}

test("Live preserves explicit comparison during inventory outage and reload", async ({ browser }) => {
  const fixture = seedExplorerTelemetry();
  const context = await authenticatedContext(browser);
  const page = await context.newPage();
  const runtime = observeRuntime(page);
  const preferenceKey = `nexolab.live-comparison.v1:${encodeURIComponent(organizationId)}`;
  const remembered = ["previous-channel"];
  const identity = [
    "edge-live-issue-400",
    fixture.equipmentId,
    fixture.channels[0]!,
    "temperature.probe",
    "degC",
  ];
  const explicit = identity.map((part) => encodeURIComponent(part)).join("|");
  const readPreference = () =>
    page.evaluate((key) => JSON.parse(localStorage.getItem(key) ?? "null"), preferenceKey);
  let inventoryFailures = 0;
  await page.route("**/api/v1/telemetry/latest**", async (route) => {
    inventoryFailures += 1;
    await route.abort("failed");
  });
  await context.addInitScript(
    ({ key, keys }) => {
      if (window.location.protocol !== "about:") {
        localStorage.setItem(key, JSON.stringify({ version: 1, keys }));
      }
    },
    { key: preferenceKey, keys: remembered },
  );

  try {
    await page.goto(`/live?compare=${encodeURIComponent(explicit)}&range=1h`);
    await expect.poll(() => inventoryFailures).toBeGreaterThan(0);
    await expect(page.getByRole("button", { name: "Повторити", exact: true })).toBeVisible();
    await expect.poll(() => new URL(page.url()).searchParams.getAll("compare")).toEqual([explicit]);
    await expect.poll(readPreference).toEqual({ version: 1, keys: remembered });

    const beforeReload = inventoryFailures;
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect.poll(() => inventoryFailures).toBeGreaterThan(beforeReload);
    await expect(page.getByRole("button", { name: "Повторити", exact: true })).toBeVisible();
    await expect.poll(() => new URL(page.url()).searchParams.getAll("compare")).toEqual([explicit]);
    await expect.poll(readPreference).toEqual({ version: 1, keys: remembered });

    await page.unroute("**/api/v1/telemetry/latest**");
    await page.getByRole("button", { name: "Повторити", exact: true }).click();
    await expect(page.getByTestId("live-selected-context")).toContainText(fixture.equipmentId);
    await expect.poll(readPreference).toEqual({ version: 1, keys: [explicit] });
    await expect.poll(() => new URL(page.url()).searchParams.getAll("compare")).toEqual([explicit]);
    expect(runtime.acquisitionMutations).toEqual([]);
  } finally {
    await context.close();
  }
});

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
       'temperature.probe',
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
    [nodeId, equipmentId, `perf-${index + 1}`, "temperature.probe", "degC"].map(encodeURIComponent).join("|"),
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
      const traffic = { history: 0, aggregate: 0, historyBytes: 0, failed: 0 };
      page.on("requestfinished", async (request) => {
        const pathname = new URL(request.url()).pathname;
        if (!pathname.includes("/api/v1/telemetry/history")) return;
        if (pathname.endsWith("/history/aggregate")) traffic.aggregate += 1;
        else traffic.history += 1;
        const sizes = await request.sizes().catch(() => null);
        traffic.historyBytes += sizes?.responseBodySize ?? 0;
      });
      page.on("requestfailed", (request) => {
        if (new URL(request.url()).pathname.includes("/api/v1/telemetry/history")) traffic.failed += 1;
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
VACUUM ANALYZE telemetry_samples;
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
