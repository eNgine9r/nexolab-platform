import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";

const organizationId = requiredEnvironment("NEXOLAB_DASHBOARD_ORGANIZATION_ID");
const otherOrganizationId = requiredEnvironment("NEXOLAB_DASHBOARD_OTHER_ORGANIZATION_ID");
const viewerToken = requiredEnvironment("NEXOLAB_DASHBOARD_VIEWER_TOKEN");
const evidenceDirectory = process.env.NEXOLAB_DASHBOARD_EVIDENCE_DIR ?? "dashboard-acceptance-evidence";
const composeProject = requiredEnvironment("COMPOSE_PROJECT_NAME");
const baseCompose = requiredEnvironment("NEXOLAB_DASHBOARD_BASE_COMPOSE");
const acceptanceCompose = requiredEnvironment("NEXOLAB_DASHBOARD_ACCEPTANCE_COMPOSE");
const mqttTopic = process.env.MQTT_TOPIC ?? "nexolab/telemetry";

type ObservedRequest = {
  url: string;
  method: string;
  authorization: boolean;
  organization: string | null;
};

type RuntimeRequest = { url: string; method: string };

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
      if (window.location.protocol === "about:") return;
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
      method: request.method(),
      authorization: headers.authorization?.startsWith("Bearer ") ?? false,
      organization: headers["x-organization-id"] ?? null,
    });
  });
  return requests;
}

function observeAcquisitionMutations(page: Page): RuntimeRequest[] {
  const mutations: RuntimeRequest[] = [];
  page.on("request", (request) => {
    if (["GET", "HEAD", "OPTIONS"].includes(request.method())) return;
    const url = new URL(request.url());
    const pathname = url.pathname.toLowerCase();
    if (
      pathname.includes("device-agent") ||
      pathname.includes("/discovery") ||
      pathname.includes("/configuration") ||
      pathname.includes("/config/")
    ) {
      mutations.push({ url: request.url(), method: request.method() });
    }
  });
  return mutations;
}

function observePublicRuntimeRequests(page: Page): RuntimeRequest[] {
  const publicRequests: RuntimeRequest[] = [];
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

  await test.step("load verified viewer inventory and canonical Overview history without leaking credentials", async () => {
    const context = await authenticatedContext(browser);
    const page = await context.newPage();
    const requests = observeTelemetryRequests(page);
    const acquisitionMutations = observeAcquisitionMutations(page);
    const publicRequests = observePublicRuntimeRequests(page);
    const sockets = observeWebSockets(page);
    try {
      await page.goto("/", { waitUntil: "domcontentloaded" });
      await expect(page.getByText("Viewer Acceptance", { exact: true })).toBeVisible();
      await expect(page.getByLabel(/Організація/)).toHaveValue(organizationId);
      await expect(page.getByText("edge-live-01", { exact: true })).toBeVisible();
      await expect(page.getByText("edge-live-02", { exact: true })).toBeVisible();
      await expect(page.getByText("K106", { exact: true })).toBeVisible();
      await expect(page.getByText("M200", { exact: true })).toBeVisible();
      await expect(page.getByText("PostgreSQL history", { exact: true })).toBeVisible();
      await expect(page.getByText(/4[,.]5 °C/).first()).toBeVisible();

      const panel = page.getByTestId("overview-chart-panel");
      await expect(panel).toHaveCount(1);
      const host = panel.getByTestId("chart-renderer-host");
      await expect(host).toBeVisible();
      await expect(panel.getByTestId("chart-accessible-summary")).toContainText("XJP60D temperature history");
      await expect.poll(() => panel.locator("canvas").count()).toBeGreaterThan(0);
      await expect(panel.locator("svg")).toHaveCount(0);

      await expect.poll(() => sockets.sentTypes.includes("authenticate"), { timeout: 20_000 }).toBe(true);
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
      await expect(panel).toHaveCount(1);
      await expect.poll(() => panel.locator("canvas").count()).toBeGreaterThan(0);

      const historyRequestsBeforeInteraction = requests.filter((item) =>
        item.url.includes("/history"),
      ).length;
      const hostBeforeLivePoint = panel.getByTestId("chart-renderer-host");
      await hostBeforeLivePoint.evaluate((element) => {
        element.setAttribute("data-overview-continuity-token", "issue-413-stable-host");
      });
      const canvasBeforeLivePoint = panel.locator("canvas").first();
      await canvasBeforeLivePoint.evaluate((element) => {
        element.setAttribute("data-overview-canvas-token", "issue-413-stable-canvas");
      });

      publishLiveTemperature(5.7);
      await expect(page.getByText(/5[,.]7 °C/).first()).toBeVisible();
      await page.waitForTimeout(750);
      await expect(hostBeforeLivePoint).toHaveAttribute(
        "data-overview-continuity-token",
        "issue-413-stable-host",
      );
      await expect(canvasBeforeLivePoint).toHaveAttribute(
        "data-overview-canvas-token",
        "issue-413-stable-canvas",
      );
      expect(requests.filter((item) => item.url.includes("/history")).length).toBe(
        historyRequestsBeforeInteraction,
      );

      await panel.getByRole("button", { name: "Hide" }).first().click();
      await expect(panel.getByRole("button", { name: "Show" })).toHaveCount(1);
      await panel.getByRole("button", { name: "Solo" }).first().click();

      await host.scrollIntoViewIfNeeded();
      const box = await host.boundingBox();
      if (!box) throw new Error("Overview chart host has no bounding box");
      const cursorLayoutBefore = {
        y: box.y,
        height: box.height,
        scrollY: await page.evaluate(() => window.scrollY),
      };
      for (const xFraction of [0.68, 0.75, 0.83, 0.91]) {
        await page.mouse.move(box.x + box.width * xFraction, box.y + box.height * 0.5);
        await page.waitForTimeout(75);
        const cursorBox = await host.boundingBox();
        if (!cursorBox) throw new Error("Overview chart host disappeared during cursor inspection");
        expect(Math.abs(cursorBox.y - cursorLayoutBefore.y)).toBeLessThanOrEqual(1);
        expect(Math.abs(cursorBox.height - cursorLayoutBefore.height)).toBeLessThanOrEqual(1);
        expect(await page.evaluate(() => window.scrollY)).toBe(cursorLayoutBefore.scrollY);
      }

      await page.mouse.wheel(0, -500);
      await page.mouse.move(box.x + box.width * 0.7, box.y + box.height * 0.5);
      await page.mouse.down();
      await page.mouse.move(box.x + box.width * 0.45, box.y + box.height * 0.5, { steps: 5 });
      await page.mouse.up();
      await panel.getByRole("button", { name: "Reset zoom" }).click();
      await expect(host).toBeVisible();
      expect(requests.filter((item) => item.url.includes("/history")).length).toBe(
        historyRequestsBeforeInteraction,
      );

      for (const width of [360, 1440, 1920]) {
        await page.setViewportSize({ width, height: 900 });
        await expect(host).toBeVisible();
        await expect
          .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
          .toBe(true);
      }

      expect(acquisitionMutations).toEqual([]);
      expect(publicRequests).toEqual([]);

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
            canonicalOverviewChart: true,
            overviewHistorySvg: false,
            cursorLayoutStable: true,
            liveCanvasIdentityStable: true,
            historyRequestsAfterChartInteractions: historyRequestsBeforeInteraction,
            acquisitionMutations,
            publicRequests,
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

      await page.getByRole("button", { name: "Вийти з NEXOLAB" }).click();
      await expect(page).toHaveURL(/\/login$/);
      const clearedCredentials = await page.evaluate(() => ({
        accessToken: window.sessionStorage.getItem("nexolab.acceptance.access-token"),
        organizationId: window.sessionStorage.getItem("nexolab.acceptance.organization-id"),
        selectedOrganizationId: window.localStorage.getItem("nexolab.selectedOrganizationId"),
      }));
      expect(clearedCredentials).toEqual({
        accessToken: null,
        organizationId: null,
        selectedOrganizationId: null,
      });
      writeFileSync(
        path.join(evidenceDirectory, "logout-state.json"),
        `${JSON.stringify(clearedCredentials, null, 2)}\n`,
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
