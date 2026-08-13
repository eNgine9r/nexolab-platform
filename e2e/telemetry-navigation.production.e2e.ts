import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";

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

type RouteKey = "overview" | "refrigeration" | "energy" | "live" | "nodes" | "sessions";

type LoadingTransition = {
  pathname: string;
  text: string;
};

type RouteResourceTiming = {
  url: string;
  initiatorType: string;
  startTimeMs: number;
  durationMs: number;
  transferSizeBytes: number;
};

const canonicalRoutes: ReadonlyArray<{
  key: RouteKey;
  href: string;
  linkName: string;
  expectedPath: RegExp;
}> = [
  { key: "overview", href: "/", linkName: "Огляд", expectedPath: /\/$/ },
  {
    key: "refrigeration",
    href: "/refrigeration",
    linkName: "Холодильне обладнання",
    expectedPath: /\/refrigeration$/,
  },
  { key: "energy", href: "/energy", linkName: "Енергомоніторинг", expectedPath: /\/energy$/ },
  { key: "live", href: "/live", linkName: "Live дані", expectedPath: /\/live(?:\?.*)?$/ },
  { key: "nodes", href: "/nodes", linkName: "Вузли", expectedPath: /\/nodes$/ },
  {
    key: "sessions",
    href: "/sessions",
    linkName: "Сесії випробувань",
    expectedPath: /\/sessions$/,
  },
];

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
  await context.addInitScript(() => {
    const documentLoads = Number(
      window.sessionStorage.getItem("nexolab.route-evidence.document-loads") ?? "0",
    );
    window.sessionStorage.setItem("nexolab.route-evidence.document-loads", String(documentLoads + 1));

    const evidenceWindow = window as Window & { __nexolabLoadingTransitions?: LoadingTransition[] };
    evidenceWindow.__nexolabLoadingTransitions = [];
    const capture = () => {
      const candidates = document.querySelectorAll<HTMLElement>(
        '[aria-label*="Завантаж"], [role="status"], h1, h2, p',
      );
      for (const candidate of candidates) {
        const text = (candidate.getAttribute("aria-label") ?? candidate.textContent ?? "").trim();
        if (!/(завантаж|loading)/i.test(text)) continue;
        const style = window.getComputedStyle(candidate);
        if (style.display === "none" || style.visibility === "hidden") continue;
        const transition = { pathname: window.location.pathname, text: text.slice(0, 160) };
        if (
          !evidenceWindow.__nexolabLoadingTransitions?.some(
            (item) => item.pathname === transition.pathname && item.text === transition.text,
          )
        ) {
          evidenceWindow.__nexolabLoadingTransitions?.push(transition);
        }
      }
    };
    new MutationObserver(capture).observe(document.documentElement, { childList: true, subtree: true });
    window.addEventListener("DOMContentLoaded", capture, { once: true });
  });
  return context;
}

async function waitForRouteUsable(page: Page, route: RouteKey): Promise<void> {
  if (route === "overview") {
    await expect(page.getByRole("heading", { name: "XJP60D температури", exact: true })).toBeVisible();
    await expect(page.getByRole("region", { name: "Стан live telemetry" })).not.toContainText("Connecting");
    return;
  }
  if (route === "refrigeration") {
    await expect(
      page.getByRole("heading", { name: "Холодильне обладнання", exact: true }).first(),
    ).toBeVisible();
    await expect(page.getByLabel("Завантаження обладнання")).toHaveCount(0);
    return;
  }
  if (route === "energy") {
    await expect(page.getByRole("heading", { name: "Енергомоніторинг", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "W1", exact: true })).toBeVisible();
    return;
  }
  if (route === "live") {
    await expect(page.getByRole("button", { name: "Saved Dashboards", exact: true })).toBeVisible();
    return;
  }
  if (route === "nodes") {
    await expect(page.getByTestId("nodes-workspace")).toBeVisible();
    await expect(page.getByText("Завантаження вузлів", { exact: true })).toHaveCount(0);
    return;
  }
  await expect(page.getByRole("heading", { name: "Лабораторні випробування", exact: true })).toBeVisible();
  await expect(page.getByText("Завантаження реальних сесій…", { exact: true })).toHaveCount(0);
}

async function loadingTransitions(page: Page): Promise<LoadingTransition[]> {
  return page.evaluate(
    () =>
      (window as Window & { __nexolabLoadingTransitions?: LoadingTransition[] })
        .__nexolabLoadingTransitions ?? [],
  );
}

async function documentLoadCount(page: Page): Promise<number> {
  return page.evaluate(() =>
    Number(window.sessionStorage.getItem("nexolab.route-evidence.document-loads") ?? "0"),
  );
}

async function routeResourceTimings(page: Page): Promise<RouteResourceTiming[]> {
  return page.evaluate(() =>
    performance
      .getEntriesByType("resource")
      .filter((entry): entry is PerformanceResourceTiming => entry instanceof PerformanceResourceTiming)
      .filter((entry) => {
        const url = new URL(entry.name);
        return url.pathname.startsWith("/_next/") || url.searchParams.has("_rsc");
      })
      .map((entry) => ({
        url: entry.name,
        initiatorType: entry.initiatorType,
        startTimeMs: Math.round(entry.startTime),
        durationMs: Math.round(entry.duration),
        transferSizeBytes: entry.transferSize,
      })),
  );
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

async function navigateAndMeasure(page: Page, route: (typeof canonicalRoutes)[number]): Promise<number> {
  const startedAt = Date.now();
  await page.getByLabel("Головна навігація").getByRole("link", { name: route.linkName, exact: true }).click();
  await expect(page).toHaveURL(route.expectedPath);
  await waitForRouteUsable(page, route.key);
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

function median(values: number[]): number {
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.floor(sorted.length / 2)];
}

function overviewAlertReadCount(requests: ApiReadEvidence[], state: "active" | "acknowledged"): number {
  return apiReadCount(requests, (request) => {
    const parsed = new URL(request.url);
    return (
      parsed.pathname === "/api/v1/alerts" &&
      parsed.searchParams.get("state") === state &&
      parsed.searchParams.get("limit") === "20" &&
      parsed.searchParams.get("offset") === "0"
    );
  });
}

test("records cold time-to-usable for every canonical monitoring route", async ({ browser }) => {
  mkdirSync(evidenceDirectory, { recursive: true });
  const cold: Record<
    RouteKey,
    {
      durationMs: number;
      apiReadCounts: Record<string, number>;
      websocket: WebSocketEvidence;
      loadingTransitions: LoadingTransition[];
      routeResources: RouteResourceTiming[];
      documentLoads: number;
      acquisitionMutations: ObservedRequest[];
    }
  > = {} as never;

  for (const route of canonicalRoutes) {
    const context = await authenticatedContext(browser);
    const page = await context.newPage();
    const requests = observeRequests(page);
    const sockets = observeWebSockets(page);
    try {
      const startedAt = Date.now();
      await page.goto(route.href, { waitUntil: "domcontentloaded" });
      await waitForRouteUsable(page, route.key);
      const durationMs = Date.now() - startedAt;

      await expect(page.getByText(/demo preview/i)).toHaveCount(0);
      expect(requests.acquisitionMutations).toEqual([]);
      expect(sockets.maxConcurrent).toBeLessThanOrEqual(1);
      cold[route.key] = {
        durationMs,
        apiReadCounts: apiReadCounts(requests.apiReads),
        websocket: { ...sockets, urls: [...sockets.urls] },
        loadingTransitions: await loadingTransitions(page),
        routeResources: await routeResourceTimings(page),
        documentLoads: await documentLoadCount(page),
        acquisitionMutations: [...requests.acquisitionMutations],
      };
      expect(cold[route.key].documentLoads).toBe(1);

      if (route.key === "overview") {
        const eagerlyFetchedInventory = requests.apiReads.filter((request) => {
          const pathname = apiPath(request);
          return pathname === "/api/v1/live-dashboards/channel-inventory" || pathname === "/api/v1/nodes";
        });
        expect(eagerlyFetchedInventory).toEqual([]);
      }
    } finally {
      await context.close();
    }
  }

  writeFileSync(
    path.join(evidenceDirectory, "telemetry-navigation-cold-summary.json"),
    `${JSON.stringify(
      {
        baseline: "9ddef4445b2894f25a6e93267f497d0e5b09b970",
        routeSequence: canonicalRoutes.map((route) => route.key),
        cold,
      },
      null,
      2,
    )}\n`,
  );
});

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
    await waitForRouteUsable(page, "overview");
    await expect.poll(() => sockets.active, { timeout: 20_000 }).toBe(1);
    await expect.poll(() => countRequests(requests.telemetry, "/latest")).toBe(1);
    await expect.poll(() => countRequests(requests.telemetry, "/history")).toBe(1);
    await expect.poll(() => overviewAlertReadCount(requests.apiReads, "active")).toBe(1);
    await expect.poll(() => overviewAlertReadCount(requests.apiReads, "acknowledged")).toBe(1);

    const initialLatestRequests = countRequests(requests.telemetry, "/latest");
    const initialHistoryRequests = countRequests(requests.telemetry, "/history");
    const initialActiveAlertReads = overviewAlertReadCount(requests.apiReads, "active");
    const initialAcknowledgedAlertReads = overviewAlertReadCount(requests.apiReads, "acknowledged");
    await page.waitForTimeout(500);
    const preNavigationApiReadCounts = apiReadCounts(requests.apiReads);
    const preNavigationRouteResources = await routeResourceTimings(page);
    expect(
      apiReadCount(
        requests.apiReads,
        (request) => apiPath(request) === "/api/v1/live-dashboards/channel-inventory",
      ),
    ).toBe(0);

    const firstVisitDurationsMs: Record<RouteKey, number> = { overview: 0 } as Record<RouteKey, number>;
    for (const route of canonicalRoutes.slice(1)) {
      firstVisitDurationsMs[route.key] = await navigateAndMeasure(page, route);
    }
    firstVisitDurationsMs.overview = await navigateAndMeasure(page, canonicalRoutes[0]);

    const firstCycleCounts = {
      latest: countRequests(requests.telemetry, "/latest"),
      history: countRequests(requests.telemetry, "/history"),
      activeAlerts: overviewAlertReadCount(requests.apiReads, "active"),
      acknowledgedAlerts: overviewAlertReadCount(requests.apiReads, "acknowledged"),
      equipmentCatalog: apiReadCount(
        requests.apiReads,
        (request) => apiPath(request) === "/api/v1/equipment",
      ),
      nodeList: apiReadCount(requests.apiReads, (request) => apiPath(request) === "/api/v1/nodes"),
      sessions: apiReadCount(requests.apiReads, (request) => apiPath(request) === "/api/v1/sessions"),
    };
    expect(firstCycleCounts.latest).toBe(initialLatestRequests);
    expect(firstCycleCounts.history).toBeLessThanOrEqual(initialHistoryRequests + 2);
    expect(firstCycleCounts.activeAlerts).toBe(initialActiveAlertReads);
    expect(firstCycleCounts.acknowledgedAlerts).toBe(initialAcknowledgedAlertReads);
    expect(firstCycleCounts.equipmentCatalog).toBe(1);
    expect(firstCycleCounts.nodeList).toBe(1);
    expect(firstCycleCounts.sessions).toBe(2);

    const warmReturnSamplesMs = Object.fromEntries(
      canonicalRoutes.map((route) => [route.key, [] as number[]]),
    ) as Record<RouteKey, number[]>;
    for (let sample = 0; sample < 3; sample += 1) {
      for (const route of canonicalRoutes.slice(1)) {
        warmReturnSamplesMs[route.key].push(await navigateAndMeasure(page, route));
      }
      warmReturnSamplesMs.overview.push(await navigateAndMeasure(page, canonicalRoutes[0]));
    }
    await waitForRouteUsable(page, "overview");
    const warmReturnMedianMs = Object.fromEntries(
      canonicalRoutes.map((route) => [route.key, median(warmReturnSamplesMs[route.key])]),
    ) as Record<RouteKey, number>;

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
    const activeAlertReads = overviewAlertReadCount(requests.apiReads, "active");
    const acknowledgedAlertReads = overviewAlertReadCount(requests.apiReads, "acknowledged");

    const summary = {
      organizationId,
      routeSequence: ["overview", "refrigeration", "energy", "live", "nodes", "sessions", "overview"],
      firstVisitDurationsMs,
      warmReturnSamplesMs,
      warmReturnMedianMs,
      preNavigationApiReadCounts,
      preNavigationRouteResources,
      routeResources: await routeResourceTimings(page),
      loadingTransitions: await loadingTransitions(page),
      documentLoads: await documentLoadCount(page),
      firstCycleCounts,
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
        activeAlertReads,
        acknowledgedAlertReads,
      },
      apiReadCounts: readCounts,
      websocket: sockets,
      acquisitionMutations: requests.acquisitionMutations,
    };

    writeFileSync(
      path.join(evidenceDirectory, "telemetry-navigation-summary.json"),
      `${JSON.stringify(summary, null, 2)}\n`,
    );

    for (const durationMs of Object.values(warmReturnMedianMs)) {
      expect(durationMs).toBeLessThanOrEqual(1_000);
    }
    expect(await documentLoadCount(page)).toBe(1);
    expect(countRequests(requests.telemetry, "/latest")).toBe(initialLatestRequests);
    expect(countRequests(requests.telemetry, "/history")).toBeLessThanOrEqual(initialHistoryRequests + 8);
    expect(sockets.opened).toBe(1);
    expect(sockets.closed).toBe(0);
    expect(sockets.active).toBe(1);
    expect(sockets.maxConcurrent).toBe(1);
    expect(requests.acquisitionMutations).toEqual([]);

    await page.screenshot({
      path: path.join(evidenceDirectory, "telemetry-navigation-overview-return.png"),
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for telemetry navigation acceptance`);
  return value;
}
