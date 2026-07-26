import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";

import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";

const organizationId = requiredEnvironment("NEXOLAB_DASHBOARD_ORGANIZATION_ID");
const otherOrganizationId = requiredEnvironment("NEXOLAB_DASHBOARD_OTHER_ORGANIZATION_ID");
const viewerToken = requiredEnvironment("NEXOLAB_DASHBOARD_VIEWER_TOKEN");
const evidenceDirectory =
  process.env.NEXOLAB_DASHBOARD_EVIDENCE_DIR ?? "dashboard-acceptance-evidence";
const composeProject = requiredEnvironment("COMPOSE_PROJECT_NAME");
const baseCompose = requiredEnvironment("NEXOLAB_DASHBOARD_BASE_COMPOSE");
const acceptanceCompose = requiredEnvironment("NEXOLAB_DASHBOARD_ACCEPTANCE_COMPOSE");
const mqttTopic = process.env.MQTT_TOPIC ?? "nexolab/telemetry";

type ObservedRequest = {
  url: string;
  authorization: boolean;
  organization: string | null;
};

type WebSocketEvidence = {
  urls: string[];
  sentTypes: string[];
  sentKeys: string[][];
  receivedTypes: string[];
};

async function authenticatedContext(
  browser: Browser,
  selectedOrganizationId = organizationId,
): Promise<BrowserContext> {
  const context = await browser.newContext();
  await context.addInitScript(
    ({ accessToken, organization }) => {
      window.sessionStorage.setItem("nexolab.acceptance.access-token", accessToken);
      window.sessionStorage.setItem("nexolab.acceptance.organization-id", organization);
    },
    { accessToken: viewerToken, organization: selectedOrganizationId },
  );
  return context;
}

function observeTelemetryRequests(page: Page): ObservedRequest[] {
  const requests: ObservedRequest[] = [];
  page.on("request", (request) => {
    const url = request.url();
    if (!url.includes("/api/v1/telemetry/")) return;
    const headers = request.headers();
    requests.push({
      url,
      authorization: headers.authorization?.startsWith("Bearer ") ?? false,
      organization: headers["x-organization-id"] ?? null,
    });
  });
  return requests;
}

function observeWebSockets(page: Page): WebSocketEvidence {
  const evidence: WebSocketEvidence = {
    urls: [],
    sentTypes: [],
    sentKeys: [],
    receivedTypes: [],
  };
  page.on("websocket", (socket) => {
    evidence.urls.push(socket.url());
    socket.on("framesent", (event) => {
      try {
        const payload = JSON.parse(String(event.payload)) as Record<string, unknown>;
        evidence.sentTypes.push(typeof payload.type === "string" ? payload.type : "unknown");
        evidence.sentKeys.push(Object.keys(payload).sort());
      } catch {
        evidence.sentTypes.push("non-json");
      }
    });
    socket.on("framereceived", (event) => {
      try {
        const payload = JSON.parse(String(event.payload)) as Record<string, unknown>;
        evidence.receivedTypes.push(typeof payload.type === "string" ? payload.type : "telemetry");
      } catch {
        evidence.receivedTypes.push("non-json");
      }
    });
  });
  return evidence;
}

function publishLiveTemperature(value: number): void {
  const payload = JSON.stringify({
    event_id: randomUUID(),
    node_id: "edge-live-01",
    captured_at: new Date().toISOString(),
    metric: "temperature.probe",
    value,
    unit: "degC",
    quality: "valid",
    source: "dashboard-acceptance",
    equipment_id: "K106",
    channel_id: "106-03",
    alarm: null,
    raw_value: Math.round(value * 10),
    raw_status: 4354,
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

function rangeMilliseconds(requestUrl: string): number {
  const url = new URL(requestUrl);
  const from = url.searchParams.get("from");
  const to = url.searchParams.get("to");
  if (!from || !to) throw new Error("History request is missing from/to query parameters");
  return Date.parse(to) - Date.parse(from);
}

test("protects and renders authenticated REST, history and WebSocket telemetry", async ({ browser }) => {
  mkdirSync(evidenceDirectory, { recursive: true });

  await test.step("block anonymous dashboard before telemetry requests", async () => {
    const context = await browser.newContext();
    const page = await context.newPage();
    const requests = observeTelemetryRequests(page);
    try {
      await page.goto("/", { waitUntil: "domcontentloaded" });
      await expect(page.getByRole("heading", { name: "Потрібен вхід до системи" })).toBeVisible();
      expect(requests).toHaveLength(0);
    } finally {
      await context.close();
    }
  });

  await test.step("load verified viewer inventory and history without leaking the bearer token", async () => {
    const context = await authenticatedContext(browser);
    const page = await context.newPage();
    const requests = observeTelemetryRequests(page);
    const sockets = observeWebSockets(page);
    try {
      await page.goto("/", { waitUntil: "domcontentloaded" });
      await expect(page.getByText("Viewer Acceptance", { exact: true })).toBeVisible();
      await expect(page.getByText("NEXOLAB Dashboard Acceptance", { exact: true })).toBeVisible();
      await expect(page.getByText("edge-live-01", { exact: true })).toBeVisible();
      await expect(page.getByText("edge-live-02", { exact: true })).toBeVisible();
      await expect(page.getByText("K106", { exact: true })).toBeVisible();
      await expect(page.getByText("M200", { exact: true })).toBeVisible();
      await expect(page.getByText("PostgreSQL history", { exact: true })).toBeVisible();
      await expect(
        page.getByRole("img", { name: "Реальний графік історії температур XJP60D" }),
      ).toBeVisible();
      await expect(page.getByText(/4[,.]5 °C/).first()).toBeVisible();

      await expect
        .poll(() => sockets.sentTypes.includes("authenticate"), { timeout: 20_000 })
        .toBe(true);
      await expect
        .poll(() => sockets.receivedTypes.includes("authenticated"), { timeout: 20_000 })
        .toBe(true);
      expect(sockets.urls).toHaveLength(1);
      expect(sockets.urls[0]).not.toContain("access_token");
      expect(sockets.urls[0]).not.toContain("Bearer");
      expect(sockets.sentKeys[0]).toEqual(["access_token", "organization_id", "type"]);

      await expect.poll(() => requests.filter((item) => item.url.includes("/latest")).length).toBe(1);
      await expect.poll(() => requests.filter((item) => item.url.includes("/history")).length).toBe(1);
      expect(requests.every((item) => item.authorization)).toBe(true);
      expect(requests.every((item) => item.organization === organizationId)).toBe(true);
      expect(requests.every((item) => !item.url.includes("Bearer"))).toBe(true);
      expect(requests.every((item) => !item.url.includes("access_token"))).toBe(true);

      await page.getByRole("button", { name: "1г", exact: true }).click();
      await expect.poll(() => requests.filter((item) => item.url.includes("/history")).length).toBe(2);
      const oneHourRequest = requests.filter((item) => item.url.includes("/history")).at(-1);
      expect(oneHourRequest).toBeDefined();
      expect(rangeMilliseconds(oneHourRequest?.url ?? "")).toBe(60 * 60 * 1000);

      publishLiveTemperature(5.7);
      await expect(page.getByText(/5[,.]7 °C/).first()).toBeVisible();

      await page.screenshot({
        path: path.join(evidenceDirectory, "authenticated-live-dashboard.png"),
        fullPage: true,
      });

      writeFileSync(
        path.join(evidenceDirectory, "authenticated-dashboard-summary.json"),
        `${JSON.stringify(
          {
            anonymousTelemetryRequests: 0,
            identity: "viewer-acceptance",
            organizationId,
            inventoryNodes: ["edge-live-01", "edge-live-02"],
            inventoryEquipment: ["K106", "M200"],
            initialHistoryRangeHours: 24,
            selectedHistoryRangeHours: 1,
            websocketUrls: sockets.urls.map((value) => {
              const url = new URL(value);
              return { origin: url.origin, pathname: url.pathname, queryKeys: [...url.searchParams.keys()] };
            }),
            websocketSentTypes: sockets.sentTypes,
            websocketSentKeys: sockets.sentKeys,
            websocketReceivedTypes: sockets.receivedTypes,
            restAuthorizationObserved: requests.every((item) => item.authorization),
            liveValueAfterWebSocket: 5.7,
          },
          null,
          2,
        )}\n`,
      );
    } finally {
      await context.close();
    }
  });

  await test.step("deny a viewer that selects an organization without membership", async () => {
    const context = await authenticatedContext(browser, otherOrganizationId);
    const page = await context.newPage();
    const requests = observeTelemetryRequests(page);
    try {
      await page.goto("/", { waitUntil: "domcontentloaded" });
      await expect(page.getByRole("heading", { name: "Доступ до dashboard відхилено" })).toBeVisible();
      expect(requests).toHaveLength(0);
    } finally {
      await context.close();
    }
  });
});

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for authenticated dashboard acceptance`);
  return value;
}
