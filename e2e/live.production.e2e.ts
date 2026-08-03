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

type LiveSeed = {
  nodeId?: string;
  equipmentId: string;
  channelId: string;
  metric: string;
  value: number | null;
  unit: string;
  quality?: "valid" | "sensor_error" | "communication_error" | "unknown";
  alarm?: "low" | "high" | null;
  capturedAt: string;
  source: string;
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

function publishSample(seed: LiveSeed): void {
  const payload = JSON.stringify({
    event_id: randomUUID(),
    node_id: seed.nodeId ?? "edge-01",
    captured_at: seed.capturedAt,
    metric: seed.metric,
    value: seed.value,
    unit: seed.unit,
    quality: seed.quality ?? "valid",
    source: seed.source,
    equipment_id: seed.equipmentId,
    channel_id: seed.channelId,
    alarm: seed.alarm ?? null,
    raw_value: seed.value,
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
      "-q",
      "1",
      "-m",
      payload,
    ],
    { stdio: "pipe" },
  );
  execFileSync("sleep", ["0.5"]);
}

function seedLiveEvidence(): void {
  const now = Date.now();
  const ago = (minutes: number) => new Date(now - minutes * 60_000).toISOString();

  publishSample({
    equipmentId: "DIXELL-106",
    channelId: "106-03",
    metric: "temperature",
    value: 3.8,
    unit: "degC",
    capturedAt: ago(45),
    source: "xjp60d",
  });
  publishSample({
    equipmentId: "DIXELL-106",
    channelId: "106-03",
    metric: "temperature",
    value: null,
    unit: "degC",
    quality: "communication_error",
    capturedAt: ago(20),
    source: "xjp60d",
  });
  publishSample({
    equipmentId: "DIXELL-106",
    channelId: "106-03",
    metric: "temperature",
    value: 4.4,
    unit: "degC",
    capturedAt: ago(10),
    source: "xjp60d",
  });
  publishSample({
    equipmentId: "DIXELL-115",
    channelId: "115-04",
    metric: "temperature",
    value: 5.7,
    unit: "degC",
    capturedAt: ago(10),
    source: "xjp60d",
  });
  publishSample({
    equipmentId: "LE01MP-200",
    channelId: "200-active-power",
    metric: "electrical.power.active",
    value: 720,
    unit: "W",
    capturedAt: ago(2),
    source: "f-and-f-le-01mp",
  });
  publishSample({
    equipmentId: "LE01MP-200",
    channelId: "200-voltage",
    metric: "electrical.voltage",
    value: 230.1,
    unit: "V",
    capturedAt: ago(2),
    source: "f-and-f-le-01mp",
  });
  publishSample({
    nodeId: "edge-02",
    equipmentId: "CLIMATE-01",
    channelId: "rh-01",
    metric: "humidity.relative",
    value: 55,
    unit: "%RH",
    alarm: "high",
    capturedAt: ago(1),
    source: "climate-adapter",
  });
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

test("discovers, filters and compares real telemetry with stable history and recovery", async ({
  browser,
}) => {
  mkdirSync(evidenceDirectory, { recursive: true });
  seedLiveEvidence();
  await new Promise((resolve) => setTimeout(resolve, 2_000));

  const context = await authenticatedContext(browser);
  const page = await context.newPage();
  const requests = observeTelemetryRequests(page);

  try {
    await page.goto("/live", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Live дані" })).toBeVisible();
    const staleRow = page
      .locator("tbody tr")
      .filter({ hasText: "DIXELL-115" })
      .filter({ hasText: "115-04" })
      .filter({ hasText: "temperature" });
    await expect(staleRow).toHaveCount(1);
    await expect(staleRow.getByText("Застарілі дані", { exact: true })).toBeVisible();

    await page.getByLabel("Пошук").fill("106-03");
    await page.getByLabel("Node").selectOption("edge-01");
    await page.getByLabel("Metric").selectOption("temperature");
    await page.getByLabel("Quality").selectOption("valid");
    await page.getByLabel("Alarm").selectOption("none");
    await expect(page.getByText("1 каналів відповідають поточному запиту")).toBeVisible();

    await page
      .getByRole("checkbox", { name: /Додати канал edge-01 · DIXELL-106 · 106-03 · temperature/ })
      .check();
    await page.getByRole("button", { name: "Очистити" }).click();
    await page
      .getByRole("checkbox", {
        name: /Додати канал edge-01 · LE01MP-200 · 200-active-power · electrical.power.active/,
      })
      .check();

    await expect(page.getByRole("img", { name: /Порівняння 1 каналів у degC/ })).toBeVisible();
    await expect(page.getByRole("img", { name: /Порівняння 1 каналів у W/ })).toBeVisible();
    await expect
      .poll(async () =>
        Number(
          await page.getByRole("img", { name: /Порівняння 1 каналів у degC/ }).getAttribute("data-segments"),
        ),
      )
      .toBeGreaterThan(1);

    await page.getByRole("button", { name: "6 год" }).click();
    await expect(page).toHaveURL(/range=6h/);
    await expect
      .poll(() => requests.filter((request) => request.url.includes("/history")).length)
      .toBeGreaterThan(2);
    expect(requests.every((request) => request.authorized)).toBe(true);
    expect(requests.some((request) => request.url.includes("snapshot_at="))).toBe(true);

    let failHistory = true;
    await page.route("**/api/v1/telemetry/history**", async (route) => {
      if (failHistory) {
        failHistory = false;
        await route.abort("failed");
        return;
      }
      await route.continue();
    });
    await page.getByRole("button", { name: "24 год" }).click();
    await expect(page.getByText("Не вдалося завантажити історію")).toBeVisible();
    await page.getByRole("button", { name: "Повторити history" }).click();
    await expect(page.getByRole("img", { name: /Порівняння 1 каналів у degC/ })).toBeVisible();

    publishSample({
      equipmentId: "DIXELL-106",
      channelId: "106-03",
      metric: "temperature",
      value: 5.1,
      unit: "degC",
      capturedAt: new Date().toISOString(),
      source: "xjp60d",
    });
    await expect(page.getByText("5,1 degC", { exact: true })).toBeVisible();

    await page.screenshot({
      path: path.join(evidenceDirectory, "authenticated-live-telemetry-explorer.png"),
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for live telemetry acceptance`);
  return value;
}
