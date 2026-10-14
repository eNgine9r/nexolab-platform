import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdirSync, readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";
import { kyivInput } from "../src/features/energy/energy-export-time";

const organizationId = requiredEnvironment("NEXOLAB_DASHBOARD_ORGANIZATION_ID");
const viewerToken = requiredEnvironment("NEXOLAB_DASHBOARD_VIEWER_TOKEN");
const evidenceDirectory = process.env.NEXOLAB_DASHBOARD_EVIDENCE_DIR ?? "dashboard-acceptance-evidence";
const composeProject = requiredEnvironment("COMPOSE_PROJECT_NAME");
const baseCompose = requiredEnvironment("NEXOLAB_DASHBOARD_BASE_COMPOSE");
const acceptanceCompose = requiredEnvironment("NEXOLAB_DASHBOARD_ACCEPTANCE_COMPOSE");
const mqttTopic = process.env.MQTT_TOPIC ?? "nexolab/telemetry";
const acquisitionMetricsUrl = requiredEnvironment("NEXOLAB_ACQUISITION_METRICS_URL");
const expectedAcquisitionRate = Number(process.env.ACQUISITION_FIXTURE_REQUESTS_PER_SECOND ?? "20");

type AcquisitionMetrics = {
  acquisition: {
    normal: { physical_requests_total: number };
    service_operations: {
      discovery?: { physical_requests_total?: number };
      configuration_mutation?: { requests_total?: number };
    };
  };
};

type EnergyMetric = {
  metric: string;
  suffix: string;
  value: number | null;
  unit: string;
  rawValue: number;
  capturedAt?: string;
  nodeId?: string;
  quality?: "valid" | "sensor_error";
};

async function authenticatedContext(
  browser: Browser,
  options: Parameters<Browser["newContext"]>[0] = {},
): Promise<BrowserContext> {
  const context = await browser.newContext(options);
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

async function selectEnergyPairs(page: Page, labels: readonly string[]): Promise<void> {
  await page.getByRole("button", { name: "+ Додати параметр" }).click();
  const dialog = page.getByRole("dialog", { name: "Параметри на графіку" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Очистити вибір" }).click();
  for (const label of labels) await dialog.getByRole("checkbox", { name: label, exact: true }).check();
  await dialog.getByRole("button", { name: "Застосувати", exact: true }).click();
  await expect(dialog).toHaveCount(0);
}

function publishEnergySample(unitId: number, sample: EnergyMetric): void {
  const sdm120 = unitId === 1;
  const payload = JSON.stringify({
    event_id: randomUUID(),
    node_id: sample.nodeId ?? "edge-01",
    captured_at: sample.capturedAt ?? new Date().toISOString(),
    metric: sample.metric,
    value: sample.value,
    unit: sample.unit,
    quality: sample.quality ?? "valid",
    source: sdm120 ? "eastron-sdm120m" : "f-and-f-le-01mp",
    equipment_id: sdm120 ? "SDM120M-1" : `LE01MP-${unitId}`,
    channel_id: `${unitId}-${sample.suffix}`,
    alarm: null,
    raw_value: sample.rawValue,
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

function exportFixtureCommand(service: string, command: string[], input?: string | Buffer): Buffer {
  if (!composeProject.startsWith("nexolab-dashboard-acceptance-"))
    throw new Error("Energy export fixtures require the isolated dashboard acceptance namespace");
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
      "exec",
      "-T",
      service,
      ...command,
    ],
    { input, stdio: "pipe" },
  );
}

function seedExportFixture(): { node: string; from: string; to: string } {
  const node = `energy-export-${randomUUID().slice(0, 8)}`;
  exportFixtureCommand(
    "postgres",
    [
      "psql",
      "--username",
      process.env.POSTGRES_USER ?? "nexolab",
      "--dbname",
      process.env.POSTGRES_DB ?? "nexolab",
      "--set",
      "ON_ERROR_STOP=1",
      "--set",
      `organization_id=${organizationId}`,
      "--set",
      `node_id=${node}`,
      "--set",
      `record_id=${randomUUID()}`,
    ],
    `INSERT INTO central_nodes (id,organization_id,node_id,display_name,state,created_by) VALUES (:'record_id',:'organization_id',:'node_id','Isolated synthetic Energy export fixture','active','energy-export-acceptance');`,
  );
  const base = Math.floor(Date.now() / 1000) * 1000 - 63_000;
  for (const unitId of [200, 1]) {
    for (const [metric, suffix, unit, values] of [
      ["electrical.power.active", "export-power", "W", unitId === 200 ? [111, 222, 333] : [10, 20, 30]],
      ["electrical.voltage", "export-voltage", "V", [220, 230, 240]],
      ["electrical.current", "export-current", "A", [1, 2, 3]],
    ] as const)
      for (let index = 0; index < 3; index++) {
        if (unitId === 1 && metric === "electrical.current" && index === 1) continue;
        const invalid = unitId === 200 && metric === "electrical.voltage" && index === 1;
        publishEnergySample(unitId, {
          nodeId: node,
          metric,
          suffix,
          unit,
          value: invalid ? null : values[index],
          rawValue: values[index],
          quality: invalid ? "sensor_error" : "valid",
          capturedAt: new Date(base + index * 30_000).toISOString(),
        });
      }
  }
  publishEnergySample(200, {
    nodeId: node,
    metric: "electrical.power.active",
    suffix: "export-power",
    unit: "W",
    value: 112,
    rawValue: 112,
    capturedAt: new Date(base).toISOString(),
  });
  return { node, from: new Date(base - 1000).toISOString(), to: new Date(base + 61_000).toISOString() };
}

function exportWallInput(value: string): string {
  return kyivInput(value).replace(/:00$/, "");
}

test("energy export preserves original PostgreSQL observations, XLSX aggregation and acquisition on mobile", async ({
  browser,
}) => {
  test.setTimeout(180_000);
  mkdirSync(evidenceDirectory, { recursive: true });
  const fixture = seedExportFixture();
  const before = await readAcquisitionMetrics();
  const context = await authenticatedContext(browser, {
    timezoneId: "America/Denver",
    acceptDownloads: true,
  });
  const page = await context.newPage();
  let sockets = 0;
  const errors: string[] = [];
  page.on("websocket", () => {
    sockets += 1;
  });
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto("/energy", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Енергомоніторинг", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Експорт даних", exact: true }).first().click();
    const dialog = page.getByRole("dialog", { name: "Експорт історичних даних" });
    await expect(
      dialog.getByRole("checkbox", {
        name: `Експорт W1 · Напруга · ${fixture.node} · 200-export-voltage`,
        exact: true,
      }),
    ).toBeVisible({ timeout: 15_000 });
    await dialog.getByRole("button", { name: "Очистити вибір", exact: true }).click();
    for (const [label, unitId] of [
      ["W1", 200],
      ["SDM120M", 1],
    ] as const)
      for (const [parameter, suffix] of [
        ["Активна потужність", "power"],
        ["Напруга", "voltage"],
        ["Струм", "current"],
      ]) {
        await dialog
          .getByRole("checkbox", {
            name: `Експорт ${label} · ${parameter} · ${fixture.node} · ${unitId}-export-${suffix}`,
            exact: true,
          })
          .check();
      }
    await dialog.getByRole("button", { name: "Власний період", exact: true }).click();
    await dialog.getByLabel("Початок · Europe/Kyiv", { exact: true }).fill(exportWallInput(fixture.from));
    await dialog.getByLabel("Завершення · Europe/Kyiv", { exact: true }).fill(exportWallInput(fixture.to));
    await dialog.getByLabel("Формат", { exact: true }).selectOption("csv");
    await dialog.getByRole("button", { name: "Попередній перегляд", exact: true }).click();
    await expect(dialog.getByRole("button", { name: "Сформувати CSV", exact: true })).toBeVisible({
      timeout: 30_000,
    });
    await expect(dialog.getByLabel("Стан експорту").locator("dd").nth(0)).toHaveText("18");
    await expect(dialog.getByLabel("Стан експорту").locator("dd").nth(1)).toHaveText("7");
    expect(
      await dialog
        .getByRole("option", { name: /10 секунд/ })
        .evaluate((option) => (option as HTMLOptionElement).disabled),
    ).toBe(true);
    await dialog.getByRole("button", { name: "Сформувати CSV", exact: true }).click();
    await dialog.getByRole("button", { name: "Закрити експорт", exact: true }).click();
    await expect(page.getByRole("button", { name: /Експорт даних.*файл готовий/ })).toBeVisible({
      timeout: 30_000,
    });
    await page.getByRole("button", { name: /Експорт даних.*файл готовий/ }).click();
    const rawDownload = page.waitForEvent("download");
    await dialog.getByRole("button", { name: "Завантажити CSV", exact: true }).click();
    const rawPath = path.join(evidenceDirectory, "energy-export-original.csv");
    await (await rawDownload).saveAs(rawPath);
    exportFixtureCommand(
      "telemetry-service",
      [
        "python",
        "-c",
        `import csv,io,sys; rows=list(csv.DictReader(io.StringIO(sys.stdin.buffer.read().decode('utf-8')))); assert len(rows)==7; assert sorted(float(row['P, W']) for row in rows if row['equipment_id']=='LE01MP-200' and row['P, W'])==[111,112,222,333]; assert any(row['U, V · quality']=='sensor_error' and row['U, V']=='' for row in rows); assert all('+' in row['Дата і час · Europe/Kyiv'] and row['timestamp_utc'].endswith('Z') for row in rows)`,
      ],
      readFileSync(rawPath),
    );
    await dialog.getByRole("button", { name: "Новий експорт", exact: true }).click();
    await dialog.getByLabel("Формат", { exact: true }).selectOption("xlsx");
    await dialog.getByRole("button", { name: "Попередній перегляд", exact: true }).click();
    await expect(dialog.getByRole("button", { name: "Сформувати XLSX", exact: true })).toBeVisible({
      timeout: 30_000,
    });
    await dialog.getByLabel("Крок даних у файлі", { exact: true }).selectOption("60");
    await expect(dialog.getByRole("button", { name: "Сформувати XLSX", exact: true })).toHaveCount(0);
    await dialog.getByLabel("Мінімум", { exact: true }).check();
    await dialog.getByLabel("Максимум", { exact: true }).check();
    await dialog.getByRole("button", { name: "Попередній перегляд", exact: true }).click();
    await expect(dialog.getByRole("button", { name: "Сформувати XLSX", exact: true })).toBeVisible({
      timeout: 30_000,
    });
    await expect(dialog.getByLabel("Стан експорту").locator("dd").nth(1)).toHaveText("4");
    for (const width of [390, 768, 1440, 1920]) {
      await page.setViewportSize({ width, height: 1000 });
      const first = dialog.getByRole("button", { name: "Закрити експорт", exact: true });
      const last = dialog.getByRole("button", { name: "Сформувати XLSX", exact: true });
      await first.focus();
      await page.keyboard.press("Shift+Tab");
      await expect(last).toBeFocused();
      await page.keyboard.press("Tab");
      await expect(first).toBeFocused();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1,
        ),
      ).toBe(true);
      expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
      await dialog.screenshot({ path: path.join(evidenceDirectory, `energy-export-${width}.png`) });
    }
    await dialog.getByRole("button", { name: "Сформувати XLSX", exact: true }).click();
    await expect(dialog.getByRole("button", { name: "Завантажити XLSX", exact: true })).toBeVisible({
      timeout: 30_000,
    });
    const xlsxDownload = page.waitForEvent("download");
    await dialog.getByRole("button", { name: "Завантажити XLSX", exact: true }).click();
    const xlsxPath = path.join(evidenceDirectory, "energy-export-aggregate.xlsx");
    await (await xlsxDownload).saveAs(xlsxPath);
    exportFixtureCommand(
      "telemetry-service",
      [
        "python",
        "-c",
        `from openpyxl import load_workbook; import io,sys; workbook=load_workbook(io.BytesIO(sys.stdin.buffer.read()),read_only=True,data_only=True); rows=list(workbook['Data_1'].values); assert len(rows)==5; headers=rows[0]; assert 'bucket_start_utc' in headers; data=[row for row in rows[1:] if row[7]=='LE01MP-200']; avg=headers.index('P, W · avg'); low=headers.index('P, W · min'); high=headers.index('P, W · max'); assert abs(data[0][avg]-445/3)<1e-9 and data[1][avg]==333; assert data[0][low]==111 and data[0][high]==222; metadata=dict(list(workbook['Metadata'].values)[1:]); assert metadata['source_events']==18 and metadata['output_rows']==4 and metadata['timezone']=='Europe/Kyiv'; workbook.close()`,
      ],
      readFileSync(xlsxPath),
    );
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Експорт даних.*файл готовий/ })).toBeFocused();
    const after = await readAcquisitionMetrics();
    expect(after.acquisition.normal.physical_requests_total).toBeGreaterThan(
      before.acquisition.normal.physical_requests_total,
    );
    expect(acquisitionServiceCounters(after)).toEqual(acquisitionServiceCounters(before));
    expect(sockets).toBe(1);
    expect(errors).toEqual([]);
  } finally {
    await context.close();
    exportFixtureCommand(
      "postgres",
      [
        "psql",
        "--username",
        process.env.POSTGRES_USER ?? "nexolab",
        "--dbname",
        process.env.POSTGRES_DB ?? "nexolab",
        "--set",
        "ON_ERROR_STOP=1",
        "--set",
        `node_id=${fixture.node}`,
        "--set",
        `organization_id=${organizationId}`,
      ],
      `BEGIN;
DELETE FROM telemetry_latest WHERE node_id=:'node_id';
DELETE FROM telemetry_samples WHERE node_id=:'node_id';
DELETE FROM central_nodes WHERE node_id=:'node_id' AND organization_id=:'organization_id' AND created_by='energy-export-acceptance';
COMMIT;`,
    );
  }
});

function observeTelemetryRequests(page: Page): Array<{ url: string; authorized: boolean }> {
  const requests: Array<{ url: string; authorized: boolean }> = [];
  page.on("request", (request) => {
    if (!request.url().includes("/api/v1/telemetry/")) return;
    requests.push({
      url: request.url(),
      authorized: request.headers().authorization?.startsWith("Bearer ") ?? false,
    });
  });
  return requests;
}

function seedEnergyEvidence(): void {
  const now = Date.now();
  const history = (minutesAgo: number) => new Date(now - minutesAgo * 60_000).toISOString();

  publishEnergySample(200, {
    metric: "electrical.power.active",
    suffix: "active-power",
    value: 615,
    unit: "W",
    rawValue: 615,
    capturedAt: history(45),
  });
  publishEnergySample(200, {
    metric: "electrical.power.active",
    suffix: "active-power",
    value: 720,
    unit: "W",
    rawValue: 720,
    capturedAt: history(1),
  });

  publishEnergySample(200, {
    metric: "electrical.energy.active",
    suffix: "active-energy",
    value: 13_740.11,
    unit: "kWh",
    rawValue: 1_374_011,
    capturedAt: history(24 * 60),
  });
  publishEnergySample(200, {
    metric: "electrical.energy.active",
    suffix: "active-energy",
    value: 13_744.9,
    unit: "kWh",
    rawValue: 1_374_490,
    capturedAt: history(45),
  });
  publishEnergySample(200, {
    metric: "electrical.energy.active",
    suffix: "active-energy",
    value: 13_745.11,
    unit: "kWh",
    rawValue: 1_374_511,
    capturedAt: history(1),
  });

  for (const [unitId, power, startEnergy, energy, rawStartEnergy, rawEnergy] of [
    [201, 810, 25_391.74, 25_401.74, 2_539_174, 2_540_174],
    [202, 920, 11_290.1, 11_296.1, 1_129_010, 1_129_610],
    [203, 1030, 13_780.2, 13_786.2, 1_378_020, 1_378_620],
  ] as const) {
    publishEnergySample(unitId, {
      metric: "electrical.power.active",
      suffix: "active-power",
      value: power,
      unit: "W",
      rawValue: power,
      capturedAt: history(1),
    });
    publishEnergySample(unitId, {
      metric: "electrical.energy.active",
      suffix: "active-energy",
      value: startEnergy,
      unit: "kWh",
      rawValue: rawStartEnergy,
      capturedAt: history(24 * 60),
    });
    publishEnergySample(unitId, {
      metric: "electrical.energy.active",
      suffix: "active-energy",
      value: energy,
      unit: "kWh",
      rawValue: rawEnergy,
      capturedAt: history(1),
    });
  }

  publishEnergySample(1, {
    metric: "electrical.power.active",
    suffix: "active-power",
    value: 0,
    unit: "W",
    rawValue: 0,
    capturedAt: history(1),
  });
  publishEnergySample(1, {
    metric: "electrical.energy.active",
    suffix: "import-active-energy",
    value: 0.03,
    unit: "kWh",
    rawValue: 0x3cf5c28f,
    capturedAt: history(24 * 60),
  });
  publishEnergySample(1, {
    metric: "electrical.energy.active",
    suffix: "import-active-energy",
    value: 0.039,
    unit: "kWh",
    rawValue: 0x3d1fbe77,
    capturedAt: history(1),
  });
  publishEnergySample(1, {
    metric: "electrical.voltage",
    suffix: "voltage",
    value: 227.8,
    unit: "V",
    rawValue: 0x4363c8d3,
    capturedAt: history(1),
  });
  publishEnergySample(1, {
    metric: "electrical.current",
    suffix: "current",
    value: 0,
    unit: "A",
    rawValue: 0,
    capturedAt: history(1),
  });
  publishEnergySample(1, {
    metric: "electrical.frequency",
    suffix: "frequency",
    value: 50.04,
    unit: "Hz",
    rawValue: 0x42482487,
    capturedAt: history(1),
  });
  publishEnergySample(1, {
    metric: "electrical.power_factor",
    suffix: "power-factor",
    value: 0,
    unit: "ratio",
    rawValue: 0,
    capturedAt: history(1),
  });

  publishEnergySample(200, {
    metric: "electrical.voltage",
    suffix: "voltage",
    value: 230.1,
    unit: "V",
    rawValue: 2301,
    capturedAt: history(1),
  });
  publishEnergySample(200, {
    metric: "electrical.current",
    suffix: "current",
    value: 3.1,
    unit: "A",
    rawValue: 31,
    capturedAt: history(1),
  });
  publishEnergySample(200, {
    metric: "electrical.power_factor",
    suffix: "power-factor",
    value: 0.955,
    unit: "ratio",
    rawValue: 955,
    capturedAt: history(1),
  });
  for (const metric of [
    { metric: "electrical.frequency", suffix: "frequency", value: 50, unit: "Hz", rawValue: 5000 },
    { metric: "electrical.power.reactive", suffix: "reactive-power", value: 40, unit: "var", rawValue: 40 },
    { metric: "electrical.power.apparent", suffix: "apparent-power", value: 745, unit: "VA", rawValue: 745 },
    { metric: "temperature.internal", suffix: "internal-temperature", value: 31, unit: "degC", rawValue: 31 },
  ])
    publishEnergySample(200, { ...metric, capturedAt: history(1) });
}

async function readAcquisitionMetrics(): Promise<AcquisitionMetrics> {
  const response = await fetch(acquisitionMetricsUrl, { cache: "no-store" });
  if (!response.ok) throw new Error(`Acquisition fixture returned HTTP ${response.status}`);
  return (await response.json()) as AcquisitionMetrics;
}

function acquisitionServiceCounters(metrics: AcquisitionMetrics) {
  return {
    discovery: metrics.acquisition.service_operations.discovery?.physical_requests_total ?? 0,
    mutations: metrics.acquisition.service_operations.configuration_mutation?.requests_total ?? 0,
  };
}

function cumulativeHistoryReads(requests: Array<{ url: string; authorized: boolean }>): number {
  return requests.filter((item) => {
    const url = new URL(item.url);
    return url.pathname.endsWith("/history") && url.searchParams.get("metric") === "electrical.energy.active";
  }).length;
}

test("renders selectable heterogeneous energy meters from verified cumulative boundaries", async ({
  browser,
}) => {
  mkdirSync(evidenceDirectory, { recursive: true });
  seedEnergyEvidence();
  await new Promise((resolve) => setTimeout(resolve, 2_000));

  const context = await authenticatedContext(browser);
  const page = await context.newPage();
  const requests = observeTelemetryRequests(page);

  try {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/energy", { waitUntil: "domcontentloaded" });

    await expect(page.getByRole("heading", { name: "Енергомоніторинг" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "W1" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "W2" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "W3" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "W4" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "SDM120M" })).toBeVisible();
    await expect(page.getByText("Eastron · SDM120M", { exact: true })).toBeVisible();
    await expect(page.getByText("227,8 V", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Не підтримується", { exact: true })).toHaveCount(1);
    await expect(page.getByText("720 W", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("230,1 V", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("0,955", { exact: true }).first()).toBeVisible();

    await expect(page.getByText("Споживання", { exact: true })).toHaveCount(5);
    await expect(page.locator("summary").filter({ hasText: /^24 год$/ })).toHaveCount(5);
    await expect(page.getByText("5,00 kWh", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Період: останні 24 години", { exact: true }).first()).toBeVisible();
    await expect(page.getByText(/Накопичена енергія/i)).toHaveCount(0);
    await expect(page.getByText(/загальний лічильник/i)).toHaveCount(0);

    await expect(page.getByRole("heading", { name: "Споживання з підтвердженого лічильника" })).toBeVisible();
    await expect(page.getByText(/restart\/power-cycle доказу/i)).toBeVisible();

    const chart = page.getByTestId("energy-history-chart");
    const plot = chart.getByRole("application", { name: "Interactive telemetry plot" });
    await expect(plot).toBeVisible();
    await expect(chart.getByText("W · Збережена історія", { exact: true })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Показник" })).toHaveCount(0);
    await expect.poll(() => cumulativeHistoryReads(requests)).toBe(1);

    const noHorizontalOverflow = async () =>
      page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);
    await expect.poll(noHorizontalOverflow).toBe(true);

    const acquisitionBefore = await readAcquisitionMetrics();
    const interactionStartedAt = Date.now();

    await plot.focus();
    await plot.press("Home");
    await expect(chart.getByTestId("chart-inspector")).toContainText(
      "W1 · Активна потужність · LE01MP-200 · 200-active-power",
    );
    await expect(chart.getByTestId("chart-inspector")).toContainText("615 W");
    await plot.press("End");

    const range7d = page.getByRole("button", { name: "7 діб" });
    await range7d.click();
    await expect(range7d).toHaveAttribute("aria-pressed", "true");
    await expect(chart.getByText(/7d ·/)).toBeVisible();

    await selectEnergyPairs(page, [
      "W1 · Активна потужність",
      "W1 · Напруга",
      "W1 · Струм",
      "SDM120M · Напруга",
    ]);
    await expect(chart.getByText("W / V / A · Збережена історія", { exact: true })).toBeVisible();
    await expect(chart.getByTestId("chart-accessible-summary")).toContainText("Осей 3");
    await plot.focus();
    await plot.press("End");
    await expect(chart.getByTestId("chart-inspector")).toContainText("230.1 V");
    await expect(chart.getByTestId("chart-inspector")).toContainText("3.1 A");
    await expect(chart.getByText(/Напруга/).first()).toBeVisible();

    const legend = chart.getByLabel("Легенда графіка");
    await legend.getByRole("button", { name: "Приховати" }).first().click();
    await legend.getByRole("button", { name: "Лише цей" }).first().click();
    await chart.getByRole("button", { name: "Скинути масштаб" }).click();

    await page.setViewportSize({ width: 1920, height: 1080 });
    await expect(plot).toBeVisible();
    await expect.poll(noHorizontalOverflow).toBe(true);
    await page.waitForTimeout(1_200);

    const acquisitionAfter = await readAcquisitionMetrics();
    expect(acquisitionServiceCounters(acquisitionAfter)).toEqual(
      acquisitionServiceCounters(acquisitionBefore),
    );
    const elapsedSeconds = (Date.now() - interactionStartedAt) / 1_000;
    const physicalDelta =
      acquisitionAfter.acquisition.normal.physical_requests_total -
      acquisitionBefore.acquisition.normal.physical_requests_total;
    const observedRate = physicalDelta / elapsedSeconds;
    expect(observedRate).toBeGreaterThan(expectedAcquisitionRate * 0.7);
    expect(observedRate).toBeLessThan(expectedAcquisitionRate * 1.3);

    await page.getByRole("button", { name: "Виключити лічильник W4 з порівняння" }).click();
    await expect(page.getByRole("button", { name: "Додати лічильник W4 з порівняння" })).toBeVisible();

    await expect.poll(() => requests.some((item) => item.url.includes("/latest"))).toBe(true);
    await expect.poll(() => requests.some((item) => item.url.includes("/history"))).toBe(true);
    expect(requests.every((item) => item.authorized)).toBe(true);

    publishEnergySample(200, {
      metric: "electrical.energy.active",
      suffix: "active-energy",
      value: 13_745.23,
      unit: "kWh",
      rawValue: 1_374_523,
    });
    await expect(page.getByText("5,12 kWh", { exact: true }).first()).toBeVisible();
    await expect.poll(() => cumulativeHistoryReads(requests)).toBe(1);

    await page.screenshot({
      path: path.join(evidenceDirectory, "authenticated-energy-monitoring.png"),
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for energy acceptance`);
  return value;
}

test("energy comparison explains the final meter and supports keyboard-only selection", async ({
  browser,
}) => {
  const context = await authenticatedContext(browser);
  const page = await context.newPage();
  const mutations: string[] = [];
  page.on("request", (request) => {
    if (
      !["GET", "HEAD", "OPTIONS"].includes(request.method()) &&
      /device-agent|discovery|configuration/.test(request.url())
    )
      mutations.push(request.url());
  });
  try {
    await page.goto("/energy", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Енергомоніторинг" })).toBeVisible();
    await selectEnergyPairs(
      page,
      ["W1", "W2", "W3", "W4", "SDM120M"].map((meter) => `${meter} · Напруга`),
    );
    await page.getByRole("button", { name: "7 діб" }).click();
    const legend = page.getByTestId("energy-history-chart").getByLabel("Легенда графіка");
    await expect(legend.getByRole("button", { name: "Лише цей" }).first()).toBeVisible();
    await legend.getByRole("button", { name: "Лише цей" }).first().click();
    const before = await readAcquisitionMetrics();
    for (const width of [320, 390, 1280, 1536, 1920]) {
      await page.setViewportSize({ width, height: 900 });
      const only = page.getByRole("button", { name: "Показати лише лічильник SDM120M" });
      await only.focus();
      await page.keyboard.press("Enter");
      await expect(legend.getByRole("button", { name: "Приховати", exact: true })).toHaveCount(1);
      await expect(legend.getByRole("button", { name: "Показати", exact: true })).toHaveCount(0);
      await legend.getByRole("button", { name: "Приховати", exact: true }).click();
      await expect(legend.getByRole("button", { name: "Показати", exact: true })).toHaveCount(1);
      await only.click();
      await expect(legend.getByRole("button", { name: "Приховати", exact: true })).toHaveCount(1);
      const finalToggle = page.getByRole("button", { name: "Виключити лічильник SDM120M з порівняння" });
      await expect(finalToggle).toBeDisabled();
      await expect(finalToggle).toHaveAccessibleDescription(/Для порівняння потрібен хоча б один лічильник/);
      await expect(page.getByRole("button", { name: /^Виключити лічильник/ })).toHaveCount(1);
      await page.getByRole("button", { name: "Додати лічильник W1 з порівняння" }).click();
      await expect(finalToggle).toBeEnabled();
      await finalToggle.click();
      await expect(page.getByRole("button", { name: "Виключити лічильник W1 з порівняння" })).toBeDisabled();
      const cards = page.getByRole("region", { name: "Лічильники електроенергії" }).locator("article");
      expect(
        await cards.evaluateAll((elements) =>
          elements.every((element) => element.scrollWidth <= element.clientWidth),
        ),
      ).toBe(true);
      await expect(page.getByLabel("Вибрані параметри графіка")).toContainText("U, V");
      await expect(page.getByRole("button", { name: "7 діб" })).toHaveAttribute("aria-pressed", "true");
    }
    expect(acquisitionServiceCounters(await readAcquisitionMetrics())).toEqual(
      acquisitionServiceCounters(before),
    );
    expect(mutations).toEqual([]);
  } finally {
    await context.close();
  }
});

test("energy nine-axis selection synchronizes panels, preserves zoom and traps modal focus on mobile", async ({
  browser,
}) => {
  const context = await authenticatedContext(browser);
  const page = await context.newPage();
  let activeSockets = 0;
  let maximumSockets = 0;
  page.on("websocket", (socket) => {
    activeSockets++;
    maximumSockets = Math.max(maximumSockets, activeSockets);
    socket.on("close", () => {
      activeSockets--;
    });
  });
  try {
    await page.goto("/energy", { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("energy-history-chart")).toBeVisible();
    await page.getByRole("button", { name: "1 год", exact: true }).click();
    const labels = [
      "Активна потужність",
      "Накопичена активна енергія",
      "Напруга",
      "Струм",
      "Частота",
      "Реактивна потужність",
      "Повна потужність",
      "Коефіцієнт потужності",
      "Температура лічильника",
    ].map((metric) => `W1 · ${metric}`);
    await selectEnergyPairs(page, labels);
    const chart = page.getByTestId("energy-history-chart");
    const hosts = chart.getByTestId("chart-renderer-host");
    await expect(hosts).toHaveCount(2);
    await expect(chart.getByRole("button", { name: "Приховати", exact: true })).toHaveCount(9);
    const domains = () =>
      hosts.evaluateAll((elements) =>
        elements.map((host) => ({
          from: Number(host.getAttribute("data-chart-x-domain-from-ms")),
          to: Number(host.getAttribute("data-chart-x-domain-to-ms")),
        })),
      );
    const original = await domains();
    expect(original[0]).toEqual(original[1]);
    await hosts.first().scrollIntoViewIfNeeded();
    const bounds = await hosts.first().boundingBox();
    if (!bounds) throw new Error("Energy plot bounds unavailable");
    await page.mouse.move(bounds.x + bounds.width * 0.6, bounds.y + bounds.height * 0.5);
    await page.mouse.wheel(0, -600);
    await expect
      .poll(async () => (await domains())[0].to - (await domains())[0].from)
      .toBeLessThan(original[0].to - original[0].from);
    const zoomed = await domains();
    expect(zoomed[0]).toEqual(zoomed[1]);
    await page.getByRole("button", { name: "Прибрати W1 · Частота" }).click();
    await expect(chart.getByRole("button", { name: "Приховати", exact: true })).toHaveCount(8);
    expect((await domains())[0]).toEqual(zoomed[0]);
    await hosts.first().focus();
    await hosts.first().press("End");
    const inspectors = chart.getByTestId("chart-inspector");
    await expect(inspectors).toHaveCount(2);
    const cursorTimes = await inspectors
      .locator('[data-testid="chart-inspector-timestamp"]')
      .allTextContents();
    expect(cursorTimes).toHaveLength(2);
    expect(cursorTimes[0]).toEqual(cursorTimes[1]);
    await chart.getByRole("button", { name: "Скинути масштаб" }).first().click();
    await expect
      .poll(async () => (await domains())[0].to - (await domains())[0].from)
      .toBeGreaterThan(zoomed[0].to - zoomed[0].from);
    const reset = await domains();
    expect(reset[0]).toEqual(reset[1]);

    for (const width of [390, 768, 1440, 1920]) {
      await page.setViewportSize({ width, height: 900 });
      await page.getByRole("button", { name: "+ Додати параметр" }).click();
      const dialog = page.getByRole("dialog", { name: "Параметри на графіку" });
      await expect(dialog.getByRole("checkbox", { name: "SDM120M · Температура лічильника" })).toBeDisabled();
      const first = dialog.getByRole("button", { name: "Закрити вибір параметрів" });
      const last = dialog.getByRole("button", { name: "Застосувати", exact: true });
      await first.focus();
      await page.keyboard.press("Shift+Tab");
      await expect(last).toBeFocused();
      await page.keyboard.press("Tab");
      await expect(first).toBeFocused();
      await expect
        .poll(() =>
          page.evaluate(
            () => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1,
          ),
        )
        .toBe(true);
      await page.keyboard.press("Escape");
      await expect(dialog).toHaveCount(0);
      await expect(page.getByRole("button", { name: "+ Додати параметр" })).toBeFocused();
      await page.screenshot({
        path: path.join(evidenceDirectory, `energy-1362-${width}.png`),
        fullPage: true,
      });
    }
    expect(maximumSockets).toBe(1);
  } finally {
    await context.close();
  }
});
