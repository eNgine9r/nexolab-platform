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
    capturedAt: history(5),
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
    capturedAt: history(5),
  });

  for (const [unitId, power, energy, rawEnergy] of [
    [201, 810, 25_401.74, 2_540_174],
    [202, 920, 11_296.1, 1_129_610],
    [203, 1030, 13_786.2, 1_378_620],
  ] as const) {
    publishEnergySample(unitId, {
      metric: "electrical.power.active",
      suffix: "active-power",
      value: power,
      unit: "W",
      rawValue: power,
      capturedAt: history(4),
    });
    publishEnergySample(unitId, {
      metric: "electrical.energy.active",
      suffix: "active-energy",
      value: energy,
      unit: "kWh",
      rawValue: rawEnergy,
      capturedAt: history(4),
    });
  }

  publishEnergySample(200, {
    metric: "electrical.voltage",
    suffix: "voltage",
    value: 230.1,
    unit: "V",
    rawValue: 2301,
    capturedAt: history(3),
  });
  publishEnergySample(200, {
    metric: "electrical.current",
    suffix: "current",
    value: 3.1,
    unit: "A",
    rawValue: 31,
    capturedAt: history(3),
  });
  publishEnergySample(200, {
    metric: "electrical.power_factor",
    suffix: "power-factor",
    value: 0.955,
    unit: "ratio",
    rawValue: 955,
    capturedAt: history(3),
  });
}

test("renders verified LE-01MP cumulative kWh in latest, history and live updates", async ({ browser }) => {
  mkdirSync(evidenceDirectory, { recursive: true });
  seedEnergyEvidence();
  await new Promise((resolve) => setTimeout(resolve, 2_000));

  const context = await authenticatedContext(browser);
  const page = await context.newPage();
  const requests = observeTelemetryRequests(page);

  try {
    await page.goto("/energy", { waitUntil: "domcontentloaded" });

    await expect(page.getByRole("heading", { name: "Енергомоніторинг" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "W1" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "W2" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "W3" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "W4" })).toBeVisible();
    await expect(page.getByText("720 W", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("230,1 V", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("0,955", { exact: true }).first()).toBeVisible();
    await expect(page.getByText(/13\s745,11 kWh/, { exact: true }).first()).toBeVisible();

    await expect(page.getByRole("heading", { name: "Накопичена енергія доступна" })).toBeVisible();
    await expect(page.getByText(/загальний лічильник/i).first()).toBeVisible();
    await expect(page.getByText(/restart\/power-cycle доказу/i)).toBeVisible();

    await expect(page.getByRole("img", { name: /Історія показника Активна потужність/ })).toBeVisible();
    await page.getByLabel("Показник").selectOption("electrical.energy.active");
    await expect(
      page.getByRole("img", { name: /Історія показника Накопичена активна енергія/ }),
    ).toBeVisible();
    await expect
      .poll(() =>
        requests.some((item) => {
          const url = new URL(item.url);
          return (
            url.pathname.endsWith("/history") && url.searchParams.get("metric") === "electrical.energy.active"
          );
        }),
      )
      .toBe(true);

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
    await expect(page.getByText(/13\s745,23 kWh/, { exact: true }).first()).toBeVisible();

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
