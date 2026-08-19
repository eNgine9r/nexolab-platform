import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdirSync } from "node:fs";
import path from "node:path";

import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";

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
  value: number;
  unit: string;
  rawValue: number;
  capturedAt?: string;
};

async function authenticatedContext(browser: Browser): Promise<BrowserContext> {
  const context = await browser.newContext();
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

function publishEnergySample(unitId: number, sample: EnergyMetric): void {
  const payload = JSON.stringify({
    event_id: randomUUID(),
    node_id: "edge-01",
    captured_at: sample.capturedAt ?? new Date().toISOString(),
    metric: sample.metric,
    value: sample.value,
    unit: sample.unit,
    quality: "valid",
    source: "f-and-f-le-01mp",
    equipment_id: `LE01MP-${unitId}`,
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

test("renders selectable LE-01MP period consumption from verified cumulative boundaries", async ({
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
    await expect(page.getByText("720 W", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("230,1 V", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("0,955", { exact: true }).first()).toBeVisible();

    await expect(page.getByText("Споживання", { exact: true })).toHaveCount(4);
    await expect(page.locator("summary").filter({ hasText: /^24 год$/ })).toHaveCount(4);
    await expect(page.getByText("5,00 kWh", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Період: останні 24 години", { exact: true }).first()).toBeVisible();
    await expect(page.getByText(/Накопичена енергія/i)).toHaveCount(0);
    await expect(page.getByText(/загальний лічильник/i)).toHaveCount(0);

    await expect(page.getByRole("heading", { name: "Споживання з підтвердженого лічильника" })).toBeVisible();
    await expect(page.getByText(/restart\/power-cycle доказу/i)).toBeVisible();

    const chart = page.getByTestId("energy-history-chart");
    const plot = chart.getByRole("application", { name: "Interactive telemetry plot" });
    await expect(plot).toBeVisible();
    await expect(chart.getByText("W · canonical persisted history", { exact: true })).toBeVisible();
    await expect(
      page.getByRole("combobox", { name: "Показник" }).getByRole("option", {
        name: "Накопичена активна енергія",
      }),
    ).toHaveCount(0);
    await expect.poll(() => cumulativeHistoryReads(requests)).toBe(1);

    const noHorizontalOverflow = async () =>
      page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);
    await expect.poll(noHorizontalOverflow).toBe(true);

    const acquisitionBefore = await readAcquisitionMetrics();
    const interactionStartedAt = Date.now();

    await plot.focus();
    await plot.press("Home");
    await expect(chart.getByTestId("chart-inspector")).toContainText("W1 · LE01MP-200 · 200-active-power");
    await expect(chart.getByTestId("chart-inspector")).toContainText("615 W");
    await plot.press("End");

    const range7d = page.getByRole("button", { name: "7 діб" });
    await range7d.click();
    await expect(range7d).toHaveAttribute("aria-pressed", "true");
    await expect(chart.getByText(/7d ·/)).toBeVisible();

    await page.getByRole("combobox", { name: "Показник" }).selectOption("electrical.voltage");
    await expect(chart.getByText("V · canonical persisted history", { exact: true })).toBeVisible();
    await expect(chart.getByText(/Напруга/).first()).toBeVisible();

    const legend = chart.getByLabel("Chart legend");
    await legend.getByRole("button", { name: "Hide" }).first().click();
    await legend.getByRole("button", { name: "Solo" }).first().click();
    await chart.getByRole("button", { name: "Reset zoom" }).click();

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
