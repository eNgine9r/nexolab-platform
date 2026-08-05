import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import {
  expect,
  test,
  type Browser,
  type BrowserContext,
  type Page,
} from "@playwright/test";

const organizationId = requiredEnvironment("NEXOLAB_DASHBOARD_ORGANIZATION_ID");
const viewerToken = requiredEnvironment("NEXOLAB_DASHBOARD_VIEWER_TOKEN");
const metricsUrl = requiredEnvironment("NEXOLAB_ACQUISITION_METRICS_URL");
const evidenceDirectory =
  process.env.NEXOLAB_DASHBOARD_EVIDENCE_DIR ?? "dashboard-acceptance-evidence";
const expectedRate = Number(process.env.ACQUISITION_FIXTURE_REQUESTS_PER_SECOND ?? "20");

type MetricsPayload = {
  acquisition: {
    normal: { physical_requests_total: number };
    service_operations: {
      discovery?: { physical_requests_total?: number };
      configuration_mutation?: { requests_total?: number };
    };
  };
};

type PhaseEvidence = {
  phase: string;
  elapsedSeconds: number;
  requestDelta: number;
  requestsPerSecond: number;
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

async function readMetrics(): Promise<MetricsPayload> {
  const response = await fetch(metricsUrl, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Metrics fixture returned HTTP ${response.status}`);
  }
  return (await response.json()) as MetricsPayload;
}

async function measurePhase(
  phase: string,
  action: () => Promise<void>,
): Promise<PhaseEvidence> {
  const before = await readMetrics();
  const started = performance.now();
  await action();
  await new Promise((resolve) => setTimeout(resolve, 1200));
  const after = await readMetrics();
  const elapsedSeconds = (performance.now() - started) / 1000;
  const requestDelta =
    after.acquisition.normal.physical_requests_total -
    before.acquisition.normal.physical_requests_total;
  return {
    phase,
    elapsedSeconds,
    requestDelta,
    requestsPerSecond: requestDelta / elapsedSeconds,
  };
}

function observeControlRequests(
  page: Page,
  evidence: Array<{ method: string; url: string }>,
): void {
  page.on("request", (request) => {
    if (!request.url().includes("/api/device-agent/xjp60d")) return;
    evidence.push({ method: request.method(), url: request.url() });
  });
}

test("page navigation and browser count do not amplify physical acquisition", async ({
  browser,
}) => {
  test.setTimeout(180_000);
  const controlRequests: Array<{ method: string; url: string }> = [];
  const contexts: BrowserContext[] = [];

  const baseline = await readMetrics();
  const phases: PhaseEvidence[] = [];
  phases.push(await measurePhase("no-browser", async () => {}));

  const primary = await authenticatedContext(browser);
  contexts.push(primary);
  const overview = await primary.newPage();
  observeControlRequests(overview, controlRequests);
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

  const live = await primary.newPage();
  observeControlRequests(live, controlRequests);
  phases.push(
    await measurePhase("live-data", async () => {
      await live.goto("/live");
      await live.waitForLoadState("domcontentloaded");
    }),
  );

  const secondary = await authenticatedContext(browser);
  const tertiary = await authenticatedContext(browser);
  contexts.push(secondary, tertiary);
  const energy = await secondary.newPage();
  const refrigeration = await tertiary.newPage();
  observeControlRequests(energy, controlRequests);
  observeControlRequests(refrigeration, controlRequests);
  phases.push(
    await measurePhase("three-browser-contexts", async () => {
      await Promise.all([energy.goto("/energy"), refrigeration.goto("/refrigeration")]);
      await Promise.all([
        energy.waitForLoadState("domcontentloaded"),
        refrigeration.waitForLoadState("domcontentloaded"),
      ]);
    }),
  );

  phases.push(
    await measurePhase("websocket-reconnect", async () => {
      await primary.setOffline(true);
      await new Promise((resolve) => setTimeout(resolve, 250));
      await primary.setOffline(false);
      await live.reload();
      await live.waitForLoadState("domcontentloaded");
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
    expect(phase.requestsPerSecond, `${phase.phase} request rate`).toBeGreaterThanOrEqual(
      expectedRate - 3,
    );
    expect(phase.requestsPerSecond, `${phase.phase} request rate`).toBeLessThanOrEqual(
      expectedRate + 3,
    );
  }
  const rates = phases.map((phase) => phase.requestsPerSecond);
  expect(Math.max(...rates) - Math.min(...rates)).toBeLessThanOrEqual(3.5);
  expect(controlRequests.length).toBeGreaterThan(0);
  expect(controlRequests.every((request) => request.method === "GET")).toBe(true);
  expect(discoveryDelta).toBe(0);
  expect(mutationDelta).toBe(0);

  mkdirSync(evidenceDirectory, { recursive: true });
  writeFileSync(
    path.join(evidenceDirectory, "acquisition-ui-invariant.json"),
    JSON.stringify(
      {
        expectedRequestsPerSecond: expectedRate,
        phases,
        controlRequests,
        discoveryDelta,
        mutationDelta,
      },
      null,
      2,
    ),
  );

  for (const context of contexts.reverse()) {
    await context.close();
  }
});

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}
