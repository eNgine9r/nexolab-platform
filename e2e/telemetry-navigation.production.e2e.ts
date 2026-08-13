import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Browser, type BrowserContext, type Locator, type Page } from "@playwright/test";

const organizationId = requiredEnvironment("NEXOLAB_DASHBOARD_ORGANIZATION_ID");
const viewerToken = requiredEnvironment("NEXOLAB_DASHBOARD_VIEWER_TOKEN");
const evidenceDirectory = process.env.NEXOLAB_DASHBOARD_EVIDENCE_DIR ?? "dashboard-acceptance-evidence";

type ObservedRequest = {
  url: string;
  method: string;
};

type ApiReadEvidence = ObservedRequest & {
  key: string;
};

type WebSocketEvidence = {
  opened: number;
  closed: number;
  active: number;
  maxConcurrent: number;
  urls: string[];
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

function observeRequests(page: Page): {
  telemetry: ObservedRequest[];
  apiReads: ApiReadEvidence[];
  acquisitionMutations: ObservedRequest[];
} {
  const telemetry: ObservedRequest[] = [];
  const apiReads: ApiReadEvidence[] = [];
  const acquisitionMutations: ObservedRequest[] = [];
  page.on("request", (request) => {
    const observed = { url: request.url(), method: request.method() };
    const parsed = new URL(observed.url);
    const pathname = parsed.pathname.toLowerCase();
    if (pathname.includes("/api/v1/telemetry/")) telemetry.push(observed);
    if (["GET", "HEAD"].includes(observed.method) && pathname.startsWith("/api/")) {
      apiReads.push({
        ...observed,
        key: `${observed.method} ${parsed.pathname}${parsed.search}`,
      });
    }

    const mutating = !["GET", "HEAD", "OPTIONS"].includes(observed.method);
    const acquisitionPath =
      pathname.includes("device-agent") ||
      pathname.includes("/discovery") ||
      pathname.includes("/configuration") ||
      pathname.includes("/config/");
    if (mutating && acquisitionPath) acquisitionMutations.push(observed);
  });
  return { telemetry, apiReads, acquisitionMutations };
}

function observeWebSockets(page: Page): WebSocketEvidence {
  const evidence: WebSocketEvidence = {
    opened: 0,
    closed: 0,
    active: 0,
    maxConcurrent: 0,
    urls: [],
  };
  page.on("websocket", (socket) => {
    evidence.opened += 1;
    evidence.active += 1;
    evidence.maxConcurrent = Math.max(evidence.maxConcurrent, evidence.active);
    evidence.urls.push(socket.url());
    socket.on("close", () => {
      evidence.closed += 1;
      evidence.active = Math.max(0, evidence.active - 1);
    });
  });
  return evidence;
}

async function navigateAndMeasure(
  page: Page,
  linkName: string,
  expectedPath: RegExp,
  usableContent: Locator,
): Promise<number> {
  const startedAt = Date.now();
  await page.getByLabel("Головна навігація").getByRole("link", { name: linkName, exact: true }).click();
  await expect(page).toHaveURL(expectedPath);
  await expect(usableContent).toBeVisible();
  return Date.now() - startedAt;
}

function countRequests(requests: ObservedRequest[], fragment: string): number {
  return requests.filter((request) => request.url.includes(fragment)).length;
}

function apiReadCounts(requests: ApiReadEvidence[]): Record<string, number> {
  const counts = new Map<string, number>();
  for (const request of requests) counts.set(request.key, (counts.get(request.key) ?? 0) + 1);
  return Object.fromEntries([...counts.entries()].sort(([left], [right]) => left.localeCompare(right)));
}

function apiReadCount(requests: ApiReadEvidence[], predicate: (request: ApiReadEvidence) => boolean): number {
  return requests.filter(predicate).length;
}

function apiPath(request: ApiReadEvidence): string {
  return new URL(request.url).pathname;
}

test("keeps telemetry usable and read-model work bounded across repeated route transitions", async ({
  browser,
}) => {
  mkdirSync(evidenceDirectory, { recursive: true });
  const context = await authenticatedContext(browser);
  const page = await context.newPage();
  const requests = observeRequests(page);
  const sockets = observeWebSockets(page);

  try {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await expect(page.getByText("Viewer Acceptance", { exact: true })).toBeVisible();
    await expect(page.getByText("edge-live-01", { exact: true })).toBeVisible();
    await expect(page.getByText(/°C/).first()).toBeVisible();
    await expect.poll(() => sockets.active, { timeout: 20_000 }).toBe(1);
    await expect.poll(() => countRequests(requests.telemetry, "/latest")).toBe(1);
    await expect.poll(() => countRequests(requests.telemetry, "/history")).toBe(1);

    const initialLatestRequests = countRequests(requests.telemetry, "/latest");
    const initialHistoryRequests = countRequests(requests.telemetry, "/history");
    const routeDurationsMs: Record<string, number> = {};

    routeDurationsMs.refrigeration = await navigateAndMeasure(
      page,
      "Холодильне обладнання",
      /\/refrigeration$/,
      page.getByRole("heading", { name: "Холодильне обладнання", exact: true }).first(),
    );
    routeDurationsMs.energy = await navigateAndMeasure(
      page,
      "Енергомоніторинг",
      /\/energy$/,
      page.getByRole("heading", { name: "Енергомоніторинг", exact: true }),
    );
    await expect(page.getByRole("heading", { name: "W1", exact: true })).toBeVisible();
    routeDurationsMs.live = await navigateAndMeasure(
      page,
      "Live дані",
      /\/live(?:\?.*)?$/,
      page.getByRole("button", { name: "Saved Dashboards", exact: true }),
    );
    routeDurationsMs.nodes = await navigateAndMeasure(
      page,
      "Вузли",
      /\/nodes$/,
      page.getByTestId("nodes-workspace"),
    );
    routeDurationsMs.sessions = await navigateAndMeasure(
      page,
      "Сесії випробувань",
      /\/sessions$/,
      page.getByRole("heading", { name: "Лабораторні випробування", exact: true }),
    );
    routeDurationsMs.overviewReturn = await navigateAndMeasure(
      page,
      "Огляд",
      /\/$/,
      page.getByText("edge-live-01", { exact: true }),
    );
    await expect(page.getByText(/°C/).first()).toBeVisible();

    const readCounts = apiReadCounts(requests.apiReads);
    const securitySessionReads = apiReadCount(
      requests.apiReads,
      (request) => apiPath(request) === "/api/v1/auth/session",
    );
    const equipmentCatalogReads = apiReadCount(
      requests.apiReads,
      (request) => apiPath(request) === "/api/v1/equipment",
    );
    const layoutDraftReads = apiReadCount(requests.apiReads, (request) =>
      apiPath(request).endsWith("/layout/draft"),
    );
    const layoutPublishedReads = apiReadCount(requests.apiReads, (request) =>
      apiPath(request).endsWith("/layout/published"),
    );
    const nodeListReads = apiReadCount(requests.apiReads, (request) => apiPath(request) === "/api/v1/nodes");
    const nodeOperationalReads = apiReadCount(requests.apiReads, (request) =>
      apiPath(request).endsWith("/operational-state"),
    );
    const sessionListReads = apiReadCount(
      requests.apiReads,
      (request) => apiPath(request) === "/api/v1/sessions",
    );
    const liveDashboardInventoryReads = apiReadCount(
      requests.apiReads,
      (request) => apiPath(request) === "/api/v1/live-dashboards/channel-inventory",
    );

    expect(routeDurationsMs.overviewReturn).toBeLessThan(5_000);
    expect(countRequests(requests.telemetry, "/latest")).toBe(initialLatestRequests);
    expect(countRequests(requests.telemetry, "/history")).toBeLessThanOrEqual(initialHistoryRequests + 2);
    expect(sockets.opened).toBe(1);
    expect(sockets.closed).toBe(0);
    expect(sockets.active).toBe(1);
    expect(sockets.maxConcurrent).toBe(1);
    expect(requests.acquisitionMutations).toEqual([]);

    await page.screenshot({
      path: path.join(evidenceDirectory, "telemetry-navigation-overview-return.png"),
      fullPage: true,
    });
    writeFileSync(
      path.join(evidenceDirectory, "telemetry-navigation-summary.json"),
      `${JSON.stringify(
        {
          organizationId,
          routeSequence: ["overview", "refrigeration", "energy", "live", "nodes", "sessions", "overview"],
          routeDurationsMs,
          latestRequests: countRequests(requests.telemetry, "/latest"),
          historyRequests: countRequests(requests.telemetry, "/history"),
          readModelCounts: {
            securitySessionReads,
            equipmentCatalogReads,
            layoutDraftReads,
            layoutPublishedReads,
            nodeListReads,
            nodeOperationalReads,
            sessionListReads,
            liveDashboardInventoryReads,
          },
          apiReadCounts: readCounts,
          websocket: sockets,
          acquisitionMutations: requests.acquisitionMutations,
        },
        null,
        2,
      )}\n`,
    );
  } finally {
    await context.close();
  }
});

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for telemetry navigation acceptance`);
  return value;
}
