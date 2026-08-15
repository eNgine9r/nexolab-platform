import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import {
  buildTelemetryPointHierarchy,
  collectTelemetryPointBranchIds,
  type TelemetryPointDescriptor,
} from "../src/features/telemetry-selection/hierarchy";

import {
  expect,
  test,
  type Browser,
  type BrowserContext,
  type Page,
  type WebSocket as PlaywrightWebSocket,
} from "@playwright/test";

const organizationId = requiredEnvironment("NEXOLAB_DASHBOARD_ORGANIZATION_ID");
const viewerToken = requiredEnvironment("NEXOLAB_DASHBOARD_VIEWER_TOKEN");
const metricsUrl = requiredEnvironment("NEXOLAB_ACQUISITION_METRICS_URL");
const evidenceDirectory = process.env.NEXOLAB_DASHBOARD_EVIDENCE_DIR ?? "dashboard-acceptance-evidence";
const expectedRate = Number(process.env.ACQUISITION_FIXTURE_REQUESTS_PER_SECOND ?? "20");
const composeProject = requiredEnvironment("COMPOSE_PROJECT_NAME");
const baseCompose = requiredEnvironment("NEXOLAB_DASHBOARD_BASE_COMPOSE");
const acceptanceCompose = requiredEnvironment("NEXOLAB_DASHBOARD_ACCEPTANCE_COMPOSE");
const postgresUser = requiredEnvironment("POSTGRES_USER");
const postgresDatabase = requiredEnvironment("POSTGRES_DB");
const apiBaseUrl = requiredEnvironment("NEXT_PUBLIC_NEXOLAB_API_BASE_URL");

type MetricsPayload = {
  acquisition: {
    normal: { physical_requests_total: number };
    service_operations: {
      discovery?: { physical_requests_total?: number };
      configuration_mutation?: { requests_total?: number };
    };
  };
};

type RuntimeMetricsPayload = {
  websocket_clients: number;
  websocket_connect_total: number;
  websocket_disconnect_total: number;
};

type PhaseEvidence = {
  phase: string;
  elapsedSeconds: number;
  requestDelta: number;
  requestsPerSecond: number;
};

type ObservedRequest = {
  method: string;
  url: string;
};

type SocketDocumentEvidence = {
  document: number;
  opened: number;
  closed: number;
  active: number;
  maximum: number;
};

type SocketEvidence = {
  opened: number;
  closed: number;
  active: number;
  maximum: number;
  currentDocument: number;
  documents: SocketDocumentEvidence[];
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

function compose(args: string[]): string {
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
      ...args,
    ],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
  );
}

function postgres(sql: string): string {
  return compose([
    "exec",
    "-T",
    "postgres",
    "psql",
    "-U",
    postgresUser,
    "-d",
    postgresDatabase,
    "-v",
    "ON_ERROR_STOP=1",
    "-tAc",
    sql,
  ]);
}

function sqlString(value: string): string {
  return `'${value.replaceAll("'", "''")}'`;
}

function seedPersistedDashboard(): {
  dashboardId: string;
  dashboardName: string;
} {
  const dashboardId = randomUUID();
  const itemId = randomUUID();
  const dashboardName = `Scale acceptance ${Date.now()}`;
  const output = postgres(`
INSERT INTO live_dashboards (
  id, organization_id, name, description, owner_subject, refresh_seconds, time_window,
  version, status, created_by, updated_by, created_at, updated_at
)
VALUES (
  ${sqlString(dashboardId)}, ${sqlString(organizationId)}, ${sqlString(dashboardName)},
  'Issue 289 acquisition invariant', 'acceptance-fixture', 2, '1h', 1, 'active',
  'acceptance-fixture', 'acceptance-fixture', NOW(), NOW()
);

INSERT INTO live_dashboard_items (
  id, organization_id, dashboard_id, position, channel_ref_id, channel_id, metric,
  native_unit, visualization, color, display_unit
)
SELECT
  ${sqlString(itemId)}, ${sqlString(organizationId)}, ${sqlString(dashboardId)}, 1,
  channel.id, channel.channel_id, channel.metric_type, channel.unit, 'line', '#00C6E0', channel.unit
FROM measurement_channels AS channel
WHERE channel.organization_id = ${sqlString(organizationId)}
  AND channel.channel_id = '106-03'
  AND channel.metric_type = 'temperature.probe'
  AND channel.status = 'active'
LIMIT 1;

SELECT COUNT(*) FROM live_dashboard_items WHERE dashboard_id = ${sqlString(dashboardId)};
`);
  if (!output.trim().endsWith("1")) {
    throw new Error("Canonical 106-03 scale dashboard item was not seeded");
  }
  return { dashboardId, dashboardName };
}

async function readMetrics(): Promise<MetricsPayload> {
  const response = await fetch(metricsUrl, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Metrics fixture returned HTTP ${response.status}`);
  }
  return (await response.json()) as MetricsPayload;
}

async function readRuntimeMetrics(): Promise<RuntimeMetricsPayload> {
  const response = await fetch(`${apiBaseUrl}/metrics/json`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Telemetry runtime metrics returned HTTP ${response.status}`);
  }
  return (await response.json()) as RuntimeMetricsPayload;
}

async function waitForApiReady(): Promise<void> {
  await expect
    .poll(
      async () => {
        try {
          return (await fetch(`${apiBaseUrl}/health/ready`)).ok;
        } catch {
          return false;
        }
      },
      { timeout: 60_000 },
    )
    .toBe(true);
}

async function measurePhase(phase: string, action: () => Promise<void>): Promise<PhaseEvidence> {
  const before = await readMetrics();
  const started = performance.now();
  await action();
  await new Promise((resolve) => setTimeout(resolve, 1200));
  const after = await readMetrics();
  const elapsedSeconds = (performance.now() - started) / 1000;
  const requestDelta =
    after.acquisition.normal.physical_requests_total - before.acquisition.normal.physical_requests_total;
  return {
    phase,
    elapsedSeconds,
    requestDelta,
    requestsPerSecond: requestDelta / elapsedSeconds,
  };
}

function observePage(
  page: Page,
  evidence: {
    controlRequests: ObservedRequest[];
    telemetryRequests: ObservedRequest[];
    sockets: Record<string, SocketEvidence>;
  },
  name: string,
): void {
  const socket: SocketEvidence = {
    opened: 0,
    closed: 0,
    active: 0,
    maximum: 0,
    currentDocument: 0,
    documents: [],
  };
  evidence.sockets[name] = socket;

  let documentNumber = 0;
  let activeSockets = new Set<PlaywrightWebSocket>();

  const currentDocument = (): SocketDocumentEvidence => {
    let document = socket.documents.at(-1);
    if (!document || document.document !== documentNumber) {
      document = {
        document: documentNumber,
        opened: 0,
        closed: 0,
        active: 0,
        maximum: 0,
      };
      socket.documents.push(document);
    }
    return document;
  };

  const startDocument = () => {
    documentNumber += 1;
    activeSockets = new Set<PlaywrightWebSocket>();
    socket.currentDocument = documentNumber;
    socket.active = 0;
    currentDocument();
  };

  page.on("framenavigated", (frame) => {
    if (frame === page.mainFrame()) startDocument();
  });

  page.on("request", (request) => {
    const observed = { method: request.method(), url: request.url() };
    if (observed.url.includes("/api/device-agent/xjp60d")) {
      evidence.controlRequests.push(observed);
    }
    if (new URL(observed.url).pathname.includes("/api/v1/telemetry/")) {
      evidence.telemetryRequests.push(observed);
    }
  });

  page.on("websocket", (websocket) => {
    if (documentNumber === 0) startDocument();
    const ownerDocument = currentDocument();
    socket.opened += 1;
    ownerDocument.opened += 1;
    activeSockets.add(websocket);
    socket.active = activeSockets.size;
    ownerDocument.active = activeSockets.size;
    ownerDocument.maximum = Math.max(ownerDocument.maximum, ownerDocument.active);
    socket.maximum = Math.max(socket.maximum, ownerDocument.maximum);

    websocket.on("close", () => {
      socket.closed += 1;
      ownerDocument.closed += 1;
      activeSockets.delete(websocket);
      if (ownerDocument.document === socket.currentDocument) {
        socket.active = activeSockets.size;
        ownerDocument.active = activeSockets.size;
      }
    });
  });
}

async function openPersistedDashboard(page: Page, dashboardName: string): Promise<void> {
  await page.goto("/live", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Live Dashboards", exact: true })).toBeVisible();
  const card = page.locator("article").filter({ hasText: dashboardName });
  await expect(card).toBeVisible();
  await card.getByRole("button", { name: "Відкрити" }).click();
  await expect(page.getByRole("heading", { name: dashboardName, exact: true })).toBeVisible();
}

test("page navigation and browser count do not amplify physical acquisition", async ({ browser }) => {
  test.setTimeout(300_000);
  const observed = {
    controlRequests: [] as ObservedRequest[],
    telemetryRequests: [] as ObservedRequest[],
    sockets: {} as Record<string, SocketEvidence>,
  };
  const contexts: BrowserContext[] = [];
  const fixture = seedPersistedDashboard();

  const baseline = await readMetrics();
  const phases: PhaseEvidence[] = [];
  phases.push(await measurePhase("no-browser", async () => {}));

  const primary = await authenticatedContext(browser);
  contexts.push(primary);
  const overview = await primary.newPage();
  observePage(overview, observed, "overview-primary");
  phases.push(
    await measurePhase("overview-open", async () => {
      await overview.goto("/");
      await overview.waitForLoadState("domcontentloaded");
    }),
  );
  phases.push(
    await measurePhase("overview-refresh", async () => {
      await overview.reload();
      await overview.waitForLoadState("domcontentloaded");
    }),
  );
  const overviewRuntimeAfterRefresh = await readRuntimeMetrics();
  expect(
    overviewRuntimeAfterRefresh.websocket_clients,
    "server active WebSocket clients after overview reload settles",
  ).toBe(1);

  const live = await primary.newPage();
  observePage(live, observed, "live-primary");
  phases.push(
    await measurePhase("persisted-live-dashboard", async () => {
      await openPersistedDashboard(live, fixture.dashboardName);
    }),
  );

  const secondary = await authenticatedContext(browser);
  const tertiary = await authenticatedContext(browser);
  const sessionContext = await authenticatedContext(browser);
  contexts.push(secondary, tertiary, sessionContext);
  const energy = await secondary.newPage();
  const refrigeration = await tertiary.newPage();
  const sessions = await sessionContext.newPage();
  observePage(energy, observed, "energy-secondary");
  observePage(refrigeration, observed, "refrigeration-tertiary");
  observePage(sessions, observed, "sessions-context");
  phases.push(
    await measurePhase("concurrent-operator-surfaces", async () => {
      await Promise.all([
        energy.goto("/energy"),
        refrigeration.goto("/refrigeration"),
        sessions.goto("/sessions"),
      ]);
      await Promise.all([
        energy.waitForLoadState("domcontentloaded"),
        refrigeration.waitForLoadState("domcontentloaded"),
        sessions.waitForLoadState("domcontentloaded"),
      ]);
    }),
  );

  const additionalRoutes = ["/", "/live", "/refrigeration"] as const;
  const additionalPages: Page[] = [];
  for (const [index, route] of additionalRoutes.entries()) {
    const context = await authenticatedContext(browser);
    contexts.push(context);
    const page = await context.newPage();
    observePage(page, observed, `additional-${index + 1}`);
    additionalPages.push(page);
    await page.goto(route, { waitUntil: "domcontentloaded" });
  }
  phases.push(
    await measurePhase("additional-authenticated-contexts", async () => {
      await Promise.all(additionalPages.map((page) => page.waitForLoadState("domcontentloaded")));
    }),
  );

  phases.push(
    await measurePhase("websocket-reconnect", async () => {
      await primary.setOffline(true);
      await new Promise((resolve) => setTimeout(resolve, 250));
      await primary.setOffline(false);
      await live.reload({ waitUntil: "domcontentloaded" });
      await expect(live.getByRole("heading", { name: "Live Dashboards", exact: true })).toBeVisible();
    }),
  );

  phases.push(
    await measurePhase("telemetry-service-restart", async () => {
      compose(["restart", "telemetry-service"]);
      await waitForApiReady();
      await live.reload({ waitUntil: "domcontentloaded" });
      await expect(live.getByText(fixture.dashboardName, { exact: true })).toBeVisible();
    }),
  );

  const finalMetrics = await readMetrics();
  const discoveryDelta =
    (finalMetrics.acquisition.service_operations.discovery?.physical_requests_total ?? 0) -
    (baseline.acquisition.service_operations.discovery?.physical_requests_total ?? 0);
  const mutationDelta =
    (finalMetrics.acquisition.service_operations.configuration_mutation?.requests_total ?? 0) -
    (baseline.acquisition.service_operations.configuration_mutation?.requests_total ?? 0);

  for (const phase of phases) {
    expect(phase.requestsPerSecond, `${phase.phase} request rate`).toBeGreaterThanOrEqual(expectedRate - 3);
    expect(phase.requestsPerSecond, `${phase.phase} request rate`).toBeLessThanOrEqual(expectedRate + 3);
  }
  const rates = phases.map((phase) => phase.requestsPerSecond);
  expect(Math.max(...rates) - Math.min(...rates)).toBeLessThanOrEqual(3.5);
  expect(observed.controlRequests.length).toBeGreaterThan(0);
  expect(observed.controlRequests.every((request) => request.method === "GET")).toBe(true);
  expect(discoveryDelta).toBe(0);
  expect(mutationDelta).toBe(0);
  for (const [name, socket] of Object.entries(observed.sockets)) {
    expect(socket.maximum, `${name} physical WebSocket maximum per document`).toBeLessThanOrEqual(1);
  }

  mkdirSync(evidenceDirectory, { recursive: true });
  writeFileSync(
    path.join(evidenceDirectory, "acquisition-ui-invariant.json"),
    `${JSON.stringify(
      {
        dashboardId: fixture.dashboardId,
        expectedRequestsPerSecond: expectedRate,
        phases,
        authenticatedContexts: contexts.length,
        openPages: 2 + 3 + additionalPages.length,
        controlRequests: observed.controlRequests,
        telemetryRequests: observed.telemetryRequests,
        websocketByPage: observed.sockets,
        overviewRuntimeAfterRefresh,
        discoveryDelta,
        mutationDelta,
      },
      null,
      2,
    )}\n`,
  );

  for (const context of contexts.reverse()) {
    await context.close();
  }
});

const selectorOrganizationId = "org-selector-browser";

function selectorPoint(
  overrides: Partial<TelemetryPointDescriptor> &
    Pick<TelemetryPointDescriptor, "channelId" | "metric" | "unit">,
): TelemetryPointDescriptor {
  return {
    organizationId: selectorOrganizationId,
    laboratory: { id: "lab-main", label: "Main laboratory" },
    zone: { id: "zone-a", label: "Zone A" },
    equipmentType: { id: "energy-meter", label: "Energy meters" },
    equipment: { id: "LE-01MP", label: "LE-01MP Meter 01" },
    nodeId: "edge-01",
    channelLabel: overrides.channelId,
    metricLabel: overrides.metric,
    ...overrides,
  };
}

function selectorInventory(): TelemetryPointDescriptor[] {
  return [
    selectorPoint({ channelId: "voltage", channelLabel: "Voltage", metric: "voltage", unit: "V" }),
    selectorPoint({ channelId: "current", channelLabel: "Current", metric: "current", unit: "A" }),
    selectorPoint({
      channelId: "power",
      channelLabel: "Active power",
      metric: "active_power",
      unit: "W",
    }),
    selectorPoint({
      zone: { id: "zone-b", label: "Zone B" },
      equipmentType: { id: "temperature-controller", label: "Temperature controllers" },
      equipment: { id: "XR170C-106", label: "XR170C Unit 106" },
      channelId: "106-03",
      channelLabel: "Probe 03",
      metric: "temperature.probe",
      metricLabel: "Temperature",
      unit: "degC",
    }),
    selectorPoint({
      laboratory: { id: "lab-secondary", label: "Secondary laboratory" },
      zone: { id: "zone-c", label: "Zone C" },
      equipment: { id: "LE-01MP-02", label: "LE-01MP Meter 02" },
      channelId: "energy",
      channelLabel: "Active energy",
      metric: "active_energy",
      unit: "kWh",
    }),
  ];
}

type SelectorSsrResult = {
  markup: string;
  nodeCount: number;
  leafCount: number;
};

function renderSelectorMarkup(
  descriptors: TelemetryPointDescriptor[],
  selected: string[],
  expandedNodeIds: string[],
): SelectorSsrResult {
  const script = String.raw`
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

const root = process.cwd();
const temp = fs.mkdtempSync(path.join(root, ".tmp-selector-ssr-"));
try {
  const hierarchySource = fs.readFileSync(
    path.join(root, "src/features/telemetry-selection/hierarchy.ts"),
    "utf8",
  );
  const selectorSource = fs
    .readFileSync(
      path.join(root, "src/components/telemetry-selection/telemetry-point-selector.tsx"),
      "utf8",
    )
    .replace(
      "@/features/telemetry-selection/hierarchy",
      "./hierarchy.js",
    );
  const compilerOptions = {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
    jsx: ts.JsxEmit.ReactJSX,
    esModuleInterop: true,
  };
  const hierarchyOutput = ts.transpileModule(hierarchySource, { compilerOptions }).outputText;
  const selectorOutput = ts.transpileModule(selectorSource, { compilerOptions }).outputText;
  fs.writeFileSync(path.join(temp, "hierarchy.js"), hierarchyOutput);
  fs.writeFileSync(path.join(temp, "selector.js"), selectorOutput);

  const hierarchyModule = require(path.join(temp, "hierarchy.js"));
  const selectorModule = require(path.join(temp, "selector.js"));
  const input = JSON.parse(fs.readFileSync(0, "utf8"));
  const hierarchy = hierarchyModule.buildTelemetryPointHierarchy(
    input.descriptors,
    input.organizationId,
  );
  const markup = renderToStaticMarkup(
    React.createElement(selectorModule.TelemetryPointSelector, {
      hierarchy,
      value: input.selected,
      maxSelection: 8,
      maxVisibleNodes: 200,
      initialExpandedNodeIds: input.expandedNodeIds,
      onConfirm: () => undefined,
    }),
  );
  process.stdout.write(
    JSON.stringify({
      markup,
      nodeCount: hierarchy.nodeCount,
      leafCount: hierarchy.leafCount,
    }),
  );
} finally {
  fs.rmSync(temp, { recursive: true, force: true });
}
`;
  const output = execFileSync(process.execPath, ["-e", script], {
    cwd: process.cwd(),
    encoding: "utf8",
    input: JSON.stringify({
      descriptors,
      organizationId: selectorOrganizationId,
      selected,
      expandedNodeIds,
    }),
    env: { ...process.env, NODE_ENV: "production" },
    maxBuffer: 10 * 1024 * 1024,
  });
  return JSON.parse(output) as SelectorSsrResult;
}

test("hierarchical telemetry selector stays bounded and side-effect free in production CSS", async ({
  browser,
}) => {
  const context = await authenticatedContext(browser);
  const stylePage = await context.newPage();
  await stylePage.goto("/", { waitUntil: "domcontentloaded" });
  const stylesheetUrls = await stylePage
    .locator('link[rel="stylesheet"]')
    .evaluateAll((links) => links.map((link) => (link as HTMLLinkElement).href));
  expect(stylesheetUrls.length, "production stylesheets discovered").toBeGreaterThan(0);
  await stylePage.close();

  const inventory = selectorInventory();
  const hierarchy = buildTelemetryPointHierarchy(inventory, selectorOrganizationId);
  const selectorRender = renderSelectorMarkup(
    inventory,
    [hierarchy.orderedLeafKeys[0]],
    collectTelemetryPointBranchIds(hierarchy),
  );
  expect(selectorRender.nodeCount, "SSR hierarchy node count").toBe(hierarchy.nodeCount);
  expect(selectorRender.leafCount, "SSR hierarchy leaf count").toBe(hierarchy.leafCount);
  const markup = selectorRender.markup;
  const styles = stylesheetUrls.map((href) => `<link rel="stylesheet" href="${href}">`).join("");

  const page = await context.newPage();
  let websocketCount = 0;
  const sideEffectRequests: ObservedRequest[] = [];
  page.on("websocket", () => {
    websocketCount += 1;
  });
  page.on("request", (request) => {
    const observed = { method: request.method(), url: request.url() };
    const pathname = new URL(observed.url).pathname;
    if (
      pathname.includes("/api/v1/telemetry/history") ||
      pathname.includes("/api/device-agent/") ||
      (observed.method !== "GET" && pathname.startsWith("/api/"))
    ) {
      sideEffectRequests.push(observed);
    }
  });

  await page.setViewportSize({ width: 360, height: 900 });
  await page.setContent(
    `<!doctype html><html><head>${styles}</head><body class="bg-[#06142a] p-2">${markup}</body></html>`,
    { waitUntil: "load" },
  );

  const tree = page.getByRole("tree", { name: "Точки телеметрії" });
  await expect(tree).toBeVisible();
  await expect(page.getByRole("treeitem", { name: /Main laboratory/ })).toBeVisible();
  await expect(page.getByRole("treeitem", { name: /Energy meters/ }).first()).toBeVisible();
  await expect(page.getByRole("treeitem", { name: /LE-01MP Meter 01/ })).toHaveAttribute(
    "aria-checked",
    "mixed",
  );
  await expect(page.getByRole("treeitem", { name: /Probe 03/ })).toBeVisible();

  const viewportEvidence: Array<{
    width: number;
    clientWidth: number;
    scrollWidth: number;
  }> = [];
  for (const width of [360, 1440, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    const dimensions = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }));
    viewportEvidence.push({ width, ...dimensions });
    expect(dimensions.scrollWidth, `document width at ${width}px viewport`).toBeLessThanOrEqual(
      dimensions.clientWidth,
    );
  }

  expect(websocketCount, "selector WebSocket openings").toBe(0);
  expect(sideEffectRequests, "selector history/control/configuration requests").toEqual([]);

  mkdirSync(evidenceDirectory, { recursive: true });
  writeFileSync(
    path.join(evidenceDirectory, "telemetry-point-selector-browser.json"),
    `${JSON.stringify(
      {
        hierarchyNodes: hierarchy.nodeCount,
        hierarchyLeaves: hierarchy.leafCount,
        viewportEvidence,
        websocketCount,
        sideEffectRequests,
      },
      null,
      2,
    )}\n`,
  );

  await context.close();
});

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}
