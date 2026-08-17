import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";

import { expect, test, type Browser, type BrowserContext } from "@playwright/test";

const organizationId = requiredEnvironment("NEXOLAB_DASHBOARD_ORGANIZATION_ID");
const sessionCredential = requiredEnvironment("NEXOLAB_DASHBOARD_VIEWER_TOKEN");
const composeProject = requiredEnvironment("COMPOSE_PROJECT_NAME");
const baseCompose = requiredEnvironment("NEXOLAB_DASHBOARD_BASE_COMPOSE");
const acceptanceCompose = requiredEnvironment("NEXOLAB_DASHBOARD_ACCEPTANCE_COMPOSE");
const mqttTopic = process.env.MQTT_TOPIC ?? "nexolab/telemetry";

interface RoutedSocket {
  close(options?: { code?: number; reason?: string }): Promise<void>;
}

interface RoutedSocketState {
  healthyClient: RoutedSocket | null;
  healthyServer: RoutedSocket | null;
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

function publishFreshTelemetry(value: number): void {
  const payload = JSON.stringify({
    event_id: randomUUID(),
    node_id: "edge-live-01",
    captured_at: new Date().toISOString(),
    metric: "temperature.probe",
    value,
    unit: "degC",
    quality: "valid",
    source: "issue-493-terminal-retry-acceptance",
    equipment_id: "K106",
    channel_id: "106-03",
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

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`Missing required environment variable ${name}`);
  return value;
}

test("Live Data Retry restarts one terminal shared WebSocket transport", async ({ browser }) => {
  const context = await authenticatedContext(browser);
  let outage = false;
  let routedSocketCount = 0;
  const routedSocketState: RoutedSocketState = { healthyClient: null, healthyServer: null };

  await context.routeWebSocket(/\/api\/v1\/telemetry\/live(?:\?|$)/, async (socket) => {
    routedSocketCount += 1;
    if (outage) {
      await socket.close({ code: 1012, reason: "issue-493-terminal-outage" });
      return;
    }

    routedSocketState.healthyClient = socket;
    routedSocketState.healthyServer = socket.connectToServer();
  });

  const page = await context.newPage();
  const inventoryChannel = page.getByTestId("live-inventory-panel").getByRole("cell", {
    name: "106-03",
    exact: true,
  });
  const retryButton = page.getByRole("button", { name: "Повторити", exact: true });

  try {
    await page.goto("/live?workspace=explorer", { waitUntil: "domcontentloaded" });
    await expect(page.getByText("Живий потік підключено", { exact: true })).toBeVisible();
    await expect(inventoryChannel).toBeVisible();
    expect(routedSocketCount).toBe(1);

    const baselineClient = routedSocketState.healthyClient;
    const baselineServer = routedSocketState.healthyServer;
    if (!baselineClient || !baselineServer) {
      throw new Error("Initial routed WebSocket pair was not captured");
    }

    outage = true;
    await Promise.all([
      baselineServer.close({ code: 1012, reason: "issue-493-terminal-outage" }),
      baselineClient.close({ code: 1012, reason: "issue-493-terminal-outage" }),
    ]);

    await expect(page.getByText("Live-потік офлайн", { exact: true })).toBeVisible({ timeout: 35_000 });
    await expect(inventoryChannel).toBeVisible();
    await expect(retryButton).toBeVisible();

    const attemptsAtOffline = routedSocketCount;
    expect(attemptsAtOffline).toBeGreaterThan(1);

    outage = false;
    await page.waitForTimeout(2_000);
    expect(routedSocketCount).toBe(attemptsAtOffline);
    await expect(page.getByText("Live-потік офлайн", { exact: true })).toBeVisible();

    await retryButton.click();

    await expect.poll(() => routedSocketCount).toBe(attemptsAtOffline + 1);
    publishFreshTelemetry(6.4);

    await expect(page.getByText("Живий потік підключено", { exact: true })).toBeVisible({ timeout: 20_000 });
    await expect(inventoryChannel).toBeVisible();
    await expect(page.getByText("6,4 degC", { exact: true })).toBeVisible();
    await page.waitForTimeout(1_000);
    expect(routedSocketCount).toBe(attemptsAtOffline + 1);
  } finally {
    await context.close();
  }
});
