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

function observeAlertsDomainRequests(page: Page): RuntimeRequest[] {
  const requests: RuntimeRequest[] = [];
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (pathname.startsWith("/api/v1/alerts") || pathname === "/api/v1/live-dashboards/channel-inventory") {
      requests.push({ url: request.url(), method: request.method() });
    }
  });
  return requests;
}

async function expectNoDocumentOverflow(page: Page, width: number): Promise<void> {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, `Horizontal overflow at ${width}px`).toBeLessThanOrEqual(1);
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

  await test.step("block anonymous Alerts before Alerts or inventory requests", async () => {
    for (const width of [360, 390, 430, 1440]) {
      const context = await browser.newContext({ viewport: { width, height: width < 1024 ? 844 : 900 } });
      const page = await context.newPage();
      const requests = observeAlertsDomainRequests(page);
      try {
        await page.goto("/alerts", { waitUntil: "domcontentloaded" });
        await expect(page.getByRole("heading", { name: "Потрібен вхід до системи" })).toBeVisible();
        await expect(page.getByTestId("alerts-workspace")).toHaveCount(0);
        const login = page.getByRole("link", { name: "Увійти", exact: true });
        await expect(login).toHaveAttribute("href", "/login?returnTo=%2Falerts");
        await expectNoDocumentOverflow(page, width);
        expect(requests).toHaveLength(0);
      } finally {
        await context.close();
      }
    }
  });

  await test.step("keep primary mobile Topbar hit areas at 44px without desktop growth", async () => {
    const context = await authenticatedContext(browser);
    const page = await context.newPage();
    try {
      for (const route of ["/", "/live"]) {
        await page.goto(route, { waitUntil: "domcontentloaded" });
        await expect(page.getByTestId("platform-topbar")).toBeVisible();

        for (const width of [360, 390, 430, 1440]) {
          await page.setViewportSize({ width, height: 900 });
          const menu = page.getByRole("button", { name: "Відкрити меню" });
          const primaryActions = [
            page.getByRole("link", { name: "Відкрити тривоги" }),
            page.getByRole("button", { name: "Вийти з NEXOLAB" }),
          ];
          if (width < 1024) {
            await expect(menu).toBeVisible();
            primaryActions.unshift(menu);
          } else {
            await expect(menu).toBeHidden();
          }

          for (const action of primaryActions) {
            const bounds = await action.boundingBox();
            expect(bounds).not.toBeNull();
            expect(bounds!.width).toBeGreaterThanOrEqual(width < 1024 ? 44 : 39);
            expect(bounds!.height).toBeGreaterThanOrEqual(width < 1024 ? 44 : 39);
            if (width === 1440) {
              expect(bounds!.width).toBeLessThanOrEqual(41);
              expect(bounds!.height).toBeLessThanOrEqual(41);
            }
          }
          await expectNoDocumentOverflow(page, width);
        }
      }
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
      await expect(page.getByTestId("platform-topbar").locator("[data-organization-id]")).toHaveAttribute(
        "data-organization-id",
        organizationId,
      );
      await expect(page.getByText("edge-live-01", { exact: true })).toBeVisible();
      await expect(page.getByText("edge-live-02", { exact: true })).toBeVisible();
      await expect(page.getByText("K106", { exact: true })).toBeVisible();
      await expect(page.getByText("M200", { exact: true })).toBeVisible();
      await expect(page.getByText("Історія температур", { exact: true })).toBeVisible();
      await expect(page.getByText(/4[,.]5 °C/).first()).toBeVisible();

      const panel = page.getByTestId("overview-chart-panel");
      await expect(panel).toHaveCount(1);
      const host = panel.getByTestId("chart-renderer-host");
      await expect(host).toBeVisible();
      await expect(panel.getByTestId("chart-accessible-summary")).toContainText("Історія температур XJP60D");
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

      await panel.getByRole("button", { name: "Приховати" }).first().click();
      await expect(panel.getByRole("button", { name: "Показати" })).toHaveCount(1);
      await panel.getByRole("button", { name: "Лише цей" }).first().click();

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
      await panel.getByRole("button", { name: "Скинути масштаб" }).click();
      await expect(host).toBeVisible();
      expect(requests.filter((item) => item.url.includes("/history")).length).toBe(
        historyRequestsBeforeInteraction,
      );

      const commandGrid = page.getByTestId("overview-command-grid");
      const primaryWorkspace = page.getByTestId("overview-primary-workspace");
      const attentionWorkspace = page.getByTestId("overview-attention-workspace");
      const secondaryGrid = page.getByTestId("overview-secondary-grid");
      await expect(commandGrid).toBeVisible();
      await expect(primaryWorkspace).toBeVisible();
      await expect(attentionWorkspace).toBeVisible();
      await expect(secondaryGrid).toBeVisible();
      await expect(page.getByRole("heading", { name: "Потребує уваги" })).toBeVisible();
      expect(
        await page.evaluate(() => {
          const primary = document.querySelector('[data-testid="overview-primary-workspace"]');
          const attention = document.querySelector('[data-testid="overview-attention-workspace"]');
          const secondary = document.querySelector('[data-testid="overview-secondary-grid"]');
          if (!primary || !attention || !secondary) return false;
          const primaryBeforeAttention = Boolean(
            primary.compareDocumentPosition(attention) & Node.DOCUMENT_POSITION_FOLLOWING,
          );
          const attentionBeforeSecondary = Boolean(
            attention.compareDocumentPosition(secondary) & Node.DOCUMENT_POSITION_FOLLOWING,
          );
          return primaryBeforeAttention && attentionBeforeSecondary;
        }),
      ).toBe(true);

      const contextGrid = page.getByTestId("overview-context-grid");
      await expect(page.getByRole("heading", { name: "Камери", exact: true })).toHaveCount(0);
      await expect(page.getByText("Камери не налаштовані", { exact: true })).toHaveCount(0);
      await expect(contextGrid.getByRole("heading", { name: "Активні лабораторні сесії" })).toBeVisible();
      await expect(contextGrid.getByRole("heading", { name: "Схеми обладнання" })).toBeVisible();

      for (const width of [360, 1440, 1920]) {
        await page.setViewportSize({ width, height: 900 });
        await expect(host).toBeVisible();
        await expect
          .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
          .toBe(true);

        const commandBox = await commandGrid.boundingBox();
        const primaryBox = await primaryWorkspace.boundingBox();
        const attentionBox = await attentionWorkspace.boundingBox();
        const secondaryBox = await secondaryGrid.boundingBox();
        if (!commandBox || !primaryBox || !attentionBox || !secondaryBox) {
          throw new Error(`Overview layout missing at ${width}px`);
        }

        expect(primaryBox.y).toBeLessThan(attentionBox.y);
        expect(attentionBox.y).toBeLessThan(secondaryBox.y);
        expect(Math.abs(primaryBox.x - attentionBox.x)).toBeLessThanOrEqual(2);
        expect(Math.abs(primaryBox.width - attentionBox.width)).toBeLessThanOrEqual(2);
        expect(Math.abs(primaryBox.width - commandBox.width)).toBeLessThanOrEqual(2);
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
            overviewGraphFirst: true,
            overviewPrimaryFullWidth: true,
            overviewAttentionBelowGraph: true,
            overviewSupportingStateBelow: true,
            overviewResponsiveWidths: [360, 1440, 1920],
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

test("shared header keeps account actions usable on mobile and desktop", async ({ browser }) => {
  const context = await authenticatedContext(browser);
  const page = await context.newPage();
  try {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await expect(page.getByText("Viewer Acceptance", { exact: true })).toBeVisible();
    const header = page.getByTestId("platform-topbar");
    for (const width of [320, 375, 768, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      const logout = header.getByRole("button", { name: "Вийти з NEXOLAB" });
      await expect(logout).toBeVisible();
      await expect(header.locator("[data-organization-id]")).toBeVisible();
      await expect(header.getByRole("link", { name: "Відкрити тривоги" })).toHaveAttribute("href", "/alerts");
      await expect(header.getByRole("searchbox")).toHaveCount(0);
      const selector = header.getByRole("combobox", { name: "Організація" });
      if (await selector.count()) await expect(selector).toBeVisible();
      const bounds = await header.evaluate((element) => ({
        client: element.clientWidth,
        scroll: element.scrollWidth,
      }));
      expect(bounds.scroll).toBeLessThanOrEqual(bounds.client);
    }
    await page.setViewportSize({ width: 375, height: 900 });
    await header.getByRole("button", { name: "Відкрити меню" }).focus();
    await page.keyboard.press("Tab");
    await expect(header.getByRole("link", { name: "Відкрити тривоги" })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(header.getByRole("button", { name: "Вийти з NEXOLAB" })).toBeFocused();
    const organizationSelector = header.getByRole("combobox", { name: "Організація" });
    if (await organizationSelector.count()) {
      await page.keyboard.press("Tab");
      await expect(organizationSelector).toBeFocused();
    }
    await header.getByRole("link", { name: "Відкрити тривоги" }).click();
    await expect(page).toHaveURL(/\/alerts$/);
    await page.goto("/");
    await page.getByTestId("platform-topbar").getByRole("button", { name: "Вийти з NEXOLAB" }).click();
    await expect(page).toHaveURL(/\/login$/);
  } finally {
    await context.close();
  }
});

test("refrigeration uses verified account context and blocks anonymous equipment reads", async ({
  browser,
}) => {
  const anonymous = await browser.newContext();
  try {
    const page = await anonymous.newPage();
    const equipmentReads: string[] = [];
    page.on("request", (request) => {
      if (request.url().includes("/api/v1/equipment")) equipmentReads.push(request.url());
    });
    await page.goto("/refrigeration/missing-account-fixture", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Потрібен вхід до системи" })).toBeVisible();
    expect(equipmentReads).toHaveLength(0);
  } finally {
    await anonymous.close();
  }

  const context = await authenticatedContext(browser);
  try {
    const page = await context.newPage();
    await page.setViewportSize({ width: 375, height: 900 });
    await page.goto("/refrigeration/missing-account-fixture", { waitUntil: "domcontentloaded" });
    const header = page.getByTestId("platform-topbar");
    await expect(header.getByText("Viewer Acceptance", { exact: true })).toBeVisible();
    await expect(header.locator("[data-organization-id]")).toHaveAttribute(
      "data-organization-id",
      organizationId,
    );
    await expect(page.getByRole("heading", { name: "Обладнання недоступне" })).toBeVisible();
    await expect(header.getByRole("link", { name: "Нова сесія" })).toHaveCount(0);
    await expect(header.getByRole("button", { name: "Вийти з NEXOLAB" })).toBeVisible();
    await page.goto("/refrigeration", { waitUntil: "domcontentloaded" });
    await expect(
      page.getByTestId("platform-topbar").getByText("Viewer Acceptance", { exact: true }),
    ).toBeVisible();
    const createEquipment = page.getByRole("button", { name: "Додати холодильне обладнання" });
    if (await createEquipment.count()) await expect(createEquipment).toBeDisabled();
    await page.getByTestId("platform-topbar").getByRole("button", { name: "Вийти з NEXOLAB" }).click();
    await expect(page).toHaveURL(/\/login$/);
  } finally {
    await context.close();
  }
});

test("Overview visibility dialog contains keyboard focus and restores its opener", async ({ browser }) => {
  const context = await authenticatedContext(browser);
  const page = await context.newPage();
  const mutations = observeAcquisitionMutations(page);
  try {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const opener = page.getByRole("button", { name: "Налаштувати датчики на графіку Огляду" });
    await expect(opener).toBeEnabled();
    for (const width of [320, 390, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      await opener.focus();
      await page.keyboard.press("Enter");
      const dialog = page.getByRole("dialog", { name: "Датчики на графіку Огляду" });
      await expect(dialog).toBeVisible();
      await expect
        .poll(() => dialog.evaluate((element) => element.contains(document.activeElement)))
        .toBe(true);
      const controls = await dialog
        .locator(
          "button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href]",
        )
        .count();
      for (const key of ["Tab", "Shift+Tab"]) {
        for (let index = 0; index < controls + 2; index++) {
          await page.keyboard.press(key);
          expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
        }
      }
      // Native modal inertness also prevents programmatic background focus.
      await opener.evaluate((element) => element.focus());
      expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
      expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
      await page.keyboard.press("Escape");
      await expect(dialog).toHaveCount(0);
      await expect(opener).toBeFocused();
      await page.keyboard.press("Enter");
      await expect(dialog).toBeVisible();
      await dialog.getByRole("button", { name: "Застосувати відображення" }).click();
      await expect(dialog).toHaveCount(0);
      await expect(opener).toBeFocused();
    }
    expect(mutations).toEqual([]);
  } finally {
    await context.close();
  }
});

test("Overview groups real catalog sensors and preserves display-only choices", async ({ browser }) => {
  const context = await authenticatedContext(browser);
  const page = await context.newPage();
  const mutations = observeAcquisitionMutations(page);
  const catalogRequests: Array<{ method: string; organization: string | undefined; authenticated: boolean }> =
    [];
  page.on("request", (request) => {
    if (!new URL(request.url()).pathname.startsWith("/api/v1/climate-chambers")) return;
    const headers = request.headers();
    catalogRequests.push({
      method: request.method(),
      organization: headers["x-organization-id"],
      authenticated: Boolean(headers.authorization?.startsWith("Bearer ")),
    });
  });
  // The controlled Device Agent fixture uses edge-live-01, whereas the real seeded
  // climate catalog uses edge-01. Only this read response supplies the matching test identity.
  await page.route("**/api/device-agent/xjp60d", async (route) => {
    expect(route.request().method()).toBe("GET");
    const response = await route.fetch();
    expect(response.status()).toBe(200);
    await route.fulfill({
      response,
      json: { ...(await response.json()), node_id: "edge-01", active_points: ["106-03", "106-04"] },
    });
  });
  try {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const opener = page.getByRole("button", { name: "Налаштувати датчики на графіку Огляду" });
    const dialog = page.getByRole("dialog", { name: "Датчики на графіку Огляду" });
    for (const width of [320, 390, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      await expect(opener).toBeEnabled();
      await opener.click();
      const device = dialog.getByRole("checkbox", { name: /Показувати всі датчики приладу:.*106/ });
      await expect(
        dialog.getByRole("checkbox", { name: "Показувати всі датчики камери: Кліматична камера №2" }),
      ).toBeVisible();
      await expect(device).toBeChecked();
      await dialog.getByRole("checkbox", { name: "Показувати 106-03 на Огляді", exact: true }).uncheck();
      await expect(device).toHaveAttribute("aria-checked", "mixed");
      await dialog.getByRole("searchbox").fill("106-03");
      await expect(
        dialog.getByRole("checkbox", { name: "Показувати 106-04 на Огляді", exact: true }),
      ).toHaveCount(0);
      await device.focus();
      await page.keyboard.press("Space");
      await expect(device).toBeChecked();
      await page.keyboard.press("Space");
      await expect(device).not.toBeChecked();
      await page.keyboard.press("Escape");
      await expect(opener).toBeFocused();
      await opener.click();
      const first = dialog.getByRole("checkbox", { name: "Показувати 106-03 на Огляді", exact: true });
      const second = dialog.getByRole("checkbox", { name: "Показувати 106-04 на Огляді", exact: true });
      await expect(first).toBeChecked();
      await expect(second).toBeChecked();
      await first.uncheck();
      await dialog.getByRole("button", { name: "Застосувати відображення" }).click();
      await page.reload({ waitUntil: "domcontentloaded" });
      await expect(opener).toBeEnabled();
      await opener.click();
      await expect(first).not.toBeChecked();
      await expect(second).toBeChecked();
      await expect(device).toHaveAttribute("aria-checked", "mixed");
      expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
        ),
      ).toBe(true);
      await dialog.getByRole("button", { name: "Показати всі" }).click();
      await dialog.getByRole("button", { name: "Застосувати відображення" }).click();
    }
    await page.route("**/api/v1/climate-chambers", (route) =>
      route.fulfill({
        status: 503,
        json: { detail: { message: "catalog unavailable", code: "unavailable" } },
      }),
    );
    await opener.click();
    await expect(dialog.getByRole("status")).toContainText("Каталог камер недоступний");
    await expect(
      dialog.getByRole("checkbox", { name: "Показувати 106-03 на Огляді", exact: true }),
    ).toBeChecked();
    await expect(
      dialog.getByRole("checkbox", { name: "Показувати 106-04 на Огляді", exact: true }),
    ).toBeChecked();
    await page.keyboard.press("Escape");
    expect(catalogRequests.length).toBeGreaterThan(0);
    expect(
      catalogRequests.every(
        (request) =>
          request.method === "GET" && request.organization === organizationId && request.authenticated,
      ),
    ).toBe(true);
    expect(mutations).toEqual([]);
  } finally {
    await context.close();
  }
});

test("grouped navigation preserves every destination and labels planned Lockers", async ({ browser }) => {
  const context = await authenticatedContext(browser);
  const page = await context.newPage();
  const mutations = observeAcquisitionMutations(page);
  const destinations = [
    "/",
    "/live",
    "/equipment-layouts",
    "/refrigeration",
    "/alerts",
    "/cameras",
    "/energy",
    "/sessions",
    "/reports",
    "/nodes",
    "/lockers",
    "/equipment",
    "/settings",
  ];
  try {
    for (const width of [320, 390, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/", { waitUntil: "domcontentloaded" });
      await expect(page.getByText("Viewer Acceptance", { exact: true })).toBeVisible();
      if (width < 1024)
        await page.getByTestId("platform-topbar").getByRole("button", { name: "Відкрити меню" }).click();
      const navigation = page.getByRole("navigation", { name: "Головна навігація" });
      for (const group of ["Моніторинг", "Випробування", "Адміністрування"])
        await expect(navigation.getByRole("region", { name: group })).toBeVisible();
      const links = navigation.getByRole("link");
      await expect(links).toHaveCount(destinations.length);
      await links.first().focus();
      for (let index = 0; index < destinations.length; index++) {
        await expect(links.nth(index)).toHaveAttribute("href", destinations[index]);
        await expect(links.nth(index)).toBeFocused();
        await expect(links.nth(index)).toBeInViewport();
        if (index < destinations.length - 1) await page.keyboard.press("Tab");
      }
      await expect(navigation.locator('[aria-current="page"]')).toHaveCount(1);
      const lockers = navigation.getByRole("link", { name: "Поштомати", exact: true });
      await expect(lockers).toHaveAccessibleDescription("Заплановано");
      await expect(lockers.getByText("Заплановано", { exact: true })).toBeVisible();
      await lockers.focus();
      await page.keyboard.press("Enter");
      await expect(page).toHaveURL(/\/lockers$/);
      await expect(
        page.getByTestId("platform-topbar").getByText("Viewer Acceptance", { exact: true }),
      ).toBeVisible();
      if (width < 1024)
        await expect
          .poll(() => navigation.evaluate((element) => element.getBoundingClientRect().right))
          .toBeLessThanOrEqual(0);
    }
    expect(mutations).toEqual([]);
  } finally {
    await context.close();
  }
});
