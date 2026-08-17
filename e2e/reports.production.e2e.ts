import { createHash, randomUUID } from "node:crypto";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

const frontendBaseUrl = process.env.NEXOLAB_REPORTS_BASE_URL ?? "http://127.0.0.1:3104";
const apiBaseUrl = process.env.NEXOLAB_REPORTS_API_BASE_URL ?? "http://127.0.0.1:8084";
const organizationA = required("NEXOLAB_REPORTS_ORGANIZATION_A");
const organizationB = required("NEXOLAB_REPORTS_ORGANIZATION_B");
const engineerAToken = required("NEXOLAB_REPORTS_ENGINEER_A_TOKEN");
const managerAToken = required("NEXOLAB_REPORTS_MANAGER_A_TOKEN");
const managerBToken = required("NEXOLAB_REPORTS_MANAGER_B_TOKEN");
const viewerAToken = required("NEXOLAB_REPORTS_VIEWER_A_TOKEN");
const completedSessionId = required("NEXOLAB_REPORTS_COMPLETED_SESSION_ID");
const runningSessionId = required("NEXOLAB_REPORTS_RUNNING_SESSION_ID");
const telemetryEventId = required("NEXOLAB_REPORTS_TELEMETRY_EVENT_ID");
const alertTransitionId = required("NEXOLAB_REPORTS_ALERT_TRANSITION_ID");
const stageId = "70000000-0000-0000-0000-000000000001";
const bindingId = "50000000-0000-0000-0000-000000000001";
const snapshotId = "60000000-0000-0000-0000-000000000001";
const engineerSubject = "engineer-a-reports-acceptance";

interface ReportArtifact {
  id: string;
  report_id: string;
  name: string;
  media_type: string;
  sha256: string;
  size_bytes: number;
  row_count: number | null;
}

interface ReportResponse {
  id: string;
  organization_id: string;
  session_id: string;
  version: number;
  source_sha256: string;
  manifest_sha256: string;
  generated_by: string;
  replayed?: boolean;
  artifacts: ReportArtifact[];
}

interface ReportPageResponse {
  items: ReportResponse[];
  count: number;
}

interface ReportSourceSnapshot {
  metadata: {
    telemetry_selection: {
      mode: string;
      binding_ids: string[];
      binding_count: number;
    };
  };
}

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function authHeaders(token: string, organizationId: string): Record<string, string> {
  return {
    Authorization: `Bearer ${token}`,
    "X-Organization-ID": organizationId,
    Accept: "application/json",
  };
}

async function apiContext(token?: string, organizationId?: string): Promise<APIRequestContext> {
  return request.newContext({
    baseURL: apiBaseUrl,
    extraHTTPHeaders:
      token && organizationId
        ? authHeaders(token, organizationId)
        : organizationId
          ? { "X-Organization-ID": organizationId, Accept: "application/json" }
          : { Accept: "application/json" },
  });
}

function sha256(content: Buffer): string {
  return createHash("sha256").update(content).digest("hex");
}

async function installBrowserCredentials(
  page: Page,
  accessToken: string,
  organizationId: string,
): Promise<void> {
  await page.addInitScript(
    ({ token, organization }) => {
      if (window.location.protocol === "about:") return;
      window.sessionStorage.setItem("nexolab.acceptance.access-token", token);
      window.sessionStorage.setItem("nexolab.acceptance.organization-id", organization);
      window.localStorage.setItem("nexolab.selectedOrganizationId", organization);
    },
    { token: accessToken, organization: organizationId },
  );
}

async function getReport(context: APIRequestContext, reportId: string): Promise<ReportResponse> {
  const response = await context.get(`/api/v1/reports/${reportId}`);
  expect(response.status()).toBe(200);
  return (await response.json()) as ReportResponse;
}

async function downloadArtifact(
  context: APIRequestContext,
  reportId: string,
  name: string,
): Promise<{ content: Buffer; sha256Header: string | null }> {
  const response = await context.get(`/api/v1/reports/${reportId}/artifacts/${encodeURIComponent(name)}`);
  expect(response.status()).toBe(200);
  return {
    content: await response.body(),
    sha256Header: response.headers()["x-content-sha256"] ?? null,
  };
}

async function expectNoDocumentOverflow(page: Page, width: number): Promise<void> {
  await page.setViewportSize({ width, height: 900 });
  const dimensions = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
}

test("production reports preserve immutable selected evidence across API, UI and organizations", async ({
  browser,
}) => {
  const anonymous = await apiContext(undefined, organizationA);
  const engineerA = await apiContext(engineerAToken, organizationA);
  const managerA = await apiContext(managerAToken, organizationA);
  const managerB = await apiContext(managerBToken, organizationB);
  const viewerA = await apiContext(viewerAToken, organizationA);

  try {
    const anonymousList = await anonymous.get("/api/v1/reports");
    expect(anonymousList.status()).toBe(401);

    const viewerListBefore = await viewerA.get("/api/v1/reports");
    expect(viewerListBefore.status()).toBe(200);
    expect(((await viewerListBefore.json()) as ReportPageResponse).count).toBe(0);

    const viewerGenerate = await viewerA.post(`/api/v1/reports/sessions/${completedSessionId}`, {
      headers: { "Idempotency-Key": `viewer-denied-${randomUUID()}` },
      data: {},
    });
    expect(viewerGenerate.status()).toBe(403);

    const runningGenerate = await engineerA.post(`/api/v1/reports/sessions/${runningSessionId}`, {
      headers: { "Idempotency-Key": `running-denied-${randomUUID()}` },
      data: {},
    });
    expect(runningGenerate.status()).toBe(409);
    expect((await runningGenerate.json()).detail.code).toBe("report_session_not_reportable");

    const engineerContext = await browser.newContext({ baseURL: frontendBaseUrl });
    const engineerPage = await engineerContext.newPage();
    await installBrowserCredentials(engineerPage, engineerAToken, organizationA);
    await engineerPage.goto("/reports");
    await expect(engineerPage.getByTestId("reports-workspace")).toBeVisible();
    await expect(engineerPage.getByTestId("report-generation-panel")).toBeVisible();
    await expect(engineerPage.getByTestId("report-session-select")).toHaveValue(completedSessionId);
    await expect(engineerPage.getByTestId("report-telemetry-selector")).toBeVisible();
    await expect(engineerPage.getByTestId("report-telemetry-selection-count")).toContainText("1 з 1");
    await expect(engineerPage.getByTestId("generate-report")).toBeEnabled();

    for (const width of [360, 1440, 1920]) {
      await expectNoDocumentOverflow(engineerPage, width);
    }

    await engineerPage
      .getByPlaceholder("Контрольований evidence export…")
      .fill("Production browser evidence");
    await engineerPage.getByTestId("generate-report").click();
    await expect(engineerPage.getByTestId("report-detail")).toContainText("Report version 1");
    await expect(engineerPage).not.toHaveURL(/token|access_token|bearer/i);

    const generatedPageResponse = await engineerA.get("/api/v1/reports");
    expect(generatedPageResponse.status()).toBe(200);
    const generatedPage = (await generatedPageResponse.json()) as ReportPageResponse;
    expect(generatedPage.count).toBe(1);
    const browserReport = generatedPage.items[0]!;
    expect(browserReport.organization_id).toBe(organizationA);
    expect(browserReport.session_id).toBe(completedSessionId);
    expect(browserReport.generated_by).toBe(engineerSubject);

    const browserSource = JSON.parse(
      (await downloadArtifact(engineerA, browserReport.id, "source-snapshot.json")).content.toString("utf8"),
    ) as ReportSourceSnapshot;
    expect(browserSource.metadata.telemetry_selection).toEqual({
      mode: "explicit",
      binding_ids: [bindingId],
      binding_count: 1,
    });

    const downloadPromise = engineerPage.waitForEvent("download");
    await engineerPage.getByTestId("download-telemetry.csv").click();
    const browserDownload = await downloadPromise;
    expect(browserDownload.suggestedFilename()).toBe("telemetry.csv");
    await engineerContext.close();

    const replayKey = `reports-replay-${randomUUID()}`;
    const firstReplayRequest = await engineerA.post(`/api/v1/reports/sessions/${completedSessionId}`, {
      headers: { "Idempotency-Key": replayKey },
      data: {
        expected_source_sha256: browserReport.source_sha256,
        binding_ids: [bindingId],
      },
    });
    expect(firstReplayRequest.status()).toBe(201);
    const replayCreated = (await firstReplayRequest.json()) as ReportResponse;
    expect(replayCreated.version).toBe(2);

    const replayedRequest = await engineerA.post(`/api/v1/reports/sessions/${completedSessionId}`, {
      headers: { "Idempotency-Key": replayKey },
      data: {
        expected_source_sha256: browserReport.source_sha256,
        binding_ids: [bindingId],
      },
    });
    expect(replayedRequest.status()).toBe(200);
    expect(replayedRequest.headers()["idempotent-replay"]).toBe("true");
    const replayed = (await replayedRequest.json()) as ReportResponse;
    expect(replayed.id).toBe(replayCreated.id);
    expect(replayed.replayed).toBe(true);

    const mismatchedReplay = await engineerA.post(`/api/v1/reports/sessions/${completedSessionId}`, {
      headers: { "Idempotency-Key": replayKey },
      data: {},
    });
    expect(mismatchedReplay.status()).toBe(409);
    expect((await mismatchedReplay.json()).detail.code).toBe("report_idempotency_conflict");

    const managerGenerate = await managerA.post(`/api/v1/reports/sessions/${completedSessionId}`, {
      headers: { "Idempotency-Key": `manager-version-${randomUUID()}` },
      data: {
        expected_source_sha256: browserReport.source_sha256,
        binding_ids: [bindingId],
      },
    });
    expect(managerGenerate.status()).toBe(201);
    expect(((await managerGenerate.json()) as ReportResponse).version).toBe(3);

    const report = await getReport(engineerA, browserReport.id);
    const artifacts = new Map(report.artifacts.map((artifact) => [artifact.name, artifact]));
    expect([...artifacts.keys()].sort()).toEqual([
      "alert-transitions.csv",
      "manifest.json",
      "source-snapshot.json",
      "telemetry.csv",
    ]);

    for (const name of artifacts.keys()) {
      const downloaded = await downloadArtifact(engineerA, report.id, name);
      const metadata = artifacts.get(name)!;
      expect(sha256(downloaded.content)).toBe(metadata.sha256);
      expect(downloaded.sha256Header).toBe(metadata.sha256);
      expect(downloaded.content.byteLength).toBe(metadata.size_bytes);
    }

    const telemetry = (await downloadArtifact(engineerA, report.id, "telemetry.csv")).content.toString(
      "utf8",
    );
    expect(telemetry).toContain(telemetryEventId);
    expect(telemetry).toContain(completedSessionId);
    expect(telemetry).toContain(stageId);
    expect(telemetry).toContain(bindingId);
    expect(telemetry).toContain(snapshotId);

    const alerts = (await downloadArtifact(engineerA, report.id, "alert-transitions.csv")).content.toString(
      "utf8",
    );
    expect(alerts).toContain(alertTransitionId);
    expect(alerts).toContain(engineerSubject);
    expect(alerts).toContain("alert_acknowledged");

    const manifestContent = (await downloadArtifact(engineerA, report.id, "manifest.json")).content;
    expect(sha256(manifestContent)).toBe(report.manifest_sha256);
    const manifest = JSON.parse(manifestContent.toString("utf8")) as {
      report: { id: string; source_sha256: string };
      artifacts: Array<{ name: string; sha256: string; size_bytes: number }>;
    };
    expect(manifest.report.id).toBe(report.id);
    expect(manifest.report.source_sha256).toBe(report.source_sha256);
    for (const item of manifest.artifacts) {
      const metadata = artifacts.get(item.name)!;
      expect(item.sha256).toBe(metadata.sha256);
      expect(item.size_bytes).toBe(metadata.size_bytes);
    }

    const foreignList = await managerB.get("/api/v1/reports");
    expect(foreignList.status()).toBe(200);
    expect(((await foreignList.json()) as ReportPageResponse).count).toBe(0);
    expect((await managerB.get(`/api/v1/reports/${report.id}`)).status()).toBe(404);
    expect((await managerB.get(`/api/v1/reports/${report.id}/artifacts/manifest.json`)).status()).toBe(404);

    const viewerContext = await browser.newContext({ baseURL: frontendBaseUrl });
    const viewerPage = await viewerContext.newPage();
    await installBrowserCredentials(viewerPage, viewerAToken, organizationA);
    await viewerPage.goto("/reports");
    await expect(viewerPage.getByTestId("reports-workspace")).toBeVisible();
    await expect(viewerPage.getByTestId("report-generation-panel")).toHaveCount(0);
    await expect(viewerPage.getByText("Поточна роль має read-only доступ.")).toBeVisible();
    await expect(viewerPage.getByTestId("report-detail")).toContainText("Report version");
    await viewerContext.close();
  } finally {
    await anonymous.dispose();
    await engineerA.dispose();
    await managerA.dispose();
    await managerB.dispose();
    await viewerA.dispose();
  }
});
