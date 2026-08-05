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

interface ReportArtifact {
  id: string;
  name: string;
  sha256: string;
  size_bytes: number;
}

interface ReportResponse {
  id: string;
  organization_id: string;
  session_id: string;
  version: number;
  source_sha256: string;
  manifest_sha256: string;
  artifacts: ReportArtifact[];
}

interface RenderResponse {
  id: string;
  report_id: string;
  format: "xlsx" | "pdf";
  artifact_name: string;
  manifest_sha256: string;
  sha256: string;
  size_bytes: number;
  replayed?: boolean;
}

interface OutputState {
  report_id: string;
  approval: {
    state: "generated" | "approved" | "superseded";
    approved_by: string | null;
    superseded_by_report_id: string | null;
  };
  renders: RenderResponse[];
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

async function apiContext(token: string, organizationId: string): Promise<APIRequestContext> {
  return request.newContext({
    baseURL: apiBaseUrl,
    extraHTTPHeaders: authHeaders(token, organizationId),
  });
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

async function generateReport(context: APIRequestContext, key: string): Promise<ReportResponse> {
  const response = await context.post(`/api/v1/reports/sessions/${completedSessionId}`, {
    headers: { "Idempotency-Key": key },
    data: { reason: "Rendered reports browser acceptance" },
  });
  expect(response.status()).toBe(201);
  return (await response.json()) as ReportResponse;
}

async function outputState(context: APIRequestContext, reportId: string): Promise<OutputState> {
  const response = await context.get(`/api/v1/reports/${reportId}/outputs`);
  expect(response.status()).toBe(200);
  return (await response.json()) as OutputState;
}

function sha256(content: Buffer): string {
  return createHash("sha256").update(content).digest("hex");
}

test("rendered reports remain reproducible, approved and organization isolated", async ({ browser }) => {
  const engineerA = await apiContext(engineerAToken, organizationA);
  const managerA = await apiContext(managerAToken, organizationA);
  const managerB = await apiContext(managerBToken, organizationB);
  const viewerA = await apiContext(viewerAToken, organizationA);

  try {
    const first = await generateReport(engineerA, `rendered-v1-${randomUUID()}`);
    const second = await generateReport(engineerA, `rendered-v2-${randomUUID()}`);
    const third = await generateReport(engineerA, `rendered-v3-${randomUUID()}`);
    expect(first.version).toBeGreaterThanOrEqual(1);
    expect(second.version).toBe(first.version + 1);
    expect(third.version).toBe(second.version + 1);

    for (const artifact of first.artifacts) {
      const response = await engineerA.get(
        `/api/v1/reports/${first.id}/artifacts/${encodeURIComponent(artifact.name)}`,
      );
      expect(response.status()).toBe(200);
      const content = await response.body();
      expect(sha256(content)).toBe(artifact.sha256);
      expect(content.byteLength).toBe(artifact.size_bytes);
    }

    const engineerApprove = await engineerA.post(`/api/v1/reports/${first.id}/approve`, {
      headers: { "Idempotency-Key": `engineer-approve-${randomUUID()}` },
      data: {
        expected_manifest_sha256: first.manifest_sha256,
        reason: "Engineer must not approve",
        occurred_at: new Date().toISOString(),
      },
    });
    expect(engineerApprove.status()).toBe(403);

    const managerContext = await browser.newContext({ baseURL: frontendBaseUrl });
    const managerPage = await managerContext.newPage();
    await installBrowserCredentials(managerPage, managerAToken, organizationA);
    await managerPage.goto(`/reports/${first.id}`);
    await expect(managerPage.getByTestId("rendered-report-detail")).toBeVisible();
    await expect(managerPage.getByTestId("report-output-panel")).toBeVisible();
    await expect(managerPage.getByTestId("report-approval-state")).toContainText("generated");

    await managerPage.getByTestId("render-xlsx").click();
    await expect(managerPage.getByTestId("download-render-xlsx")).toBeVisible();
    await managerPage.getByTestId("render-pdf").click();
    await expect(managerPage.getByTestId("download-render-pdf")).toBeVisible();

    const xlsxDownloadPromise = managerPage.waitForEvent("download");
    await managerPage.getByTestId("download-render-xlsx").click();
    const xlsxDownload = await xlsxDownloadPromise;
    expect(xlsxDownload.suggestedFilename()).toBe("report.xlsx");

    const pdfDownloadPromise = managerPage.waitForEvent("download");
    await managerPage.getByTestId("download-render-pdf").click();
    const pdfDownload = await pdfDownloadPromise;
    expect(pdfDownload.suggestedFilename()).toBe("protocol.pdf");

    await managerPage.getByTestId("approve-report").click();
    await expect(managerPage.getByTestId("report-approval-state")).toContainText("approved");
    await expect(managerPage.getByTestId("report-replacement-select")).toHaveValue(second.id);
    await managerPage.getByTestId("supersede-report").click();
    await expect(managerPage.getByTestId("report-approval-state")).toContainText("superseded");
    await managerContext.close();

    const firstState = await outputState(managerA, first.id);
    expect(firstState.approval.state).toBe("superseded");
    expect(firstState.approval.superseded_by_report_id).toBe(second.id);
    expect(new Set(firstState.renders.map((item) => item.format))).toEqual(new Set(["xlsx", "pdf"]));

    for (const render of firstState.renders) {
      const response = await managerA.get(`/api/v1/reports/${first.id}/renders/${render.id}`);
      expect(response.status()).toBe(200);
      const content = await response.body();
      expect(sha256(content)).toBe(render.sha256);
      expect(content.byteLength).toBe(render.size_bytes);
      expect(response.headers()["x-manifest-sha256"]).toBe(first.manifest_sha256);
    }

    const replayKey = `render-replay-${randomUUID()}`;
    const initialRender = await engineerA.post(`/api/v1/reports/${second.id}/renders/xlsx`, {
      headers: { "Idempotency-Key": replayKey },
      data: { expected_manifest_sha256: second.manifest_sha256 },
    });
    const replayRender = await engineerA.post(`/api/v1/reports/${second.id}/renders/xlsx`, {
      headers: { "Idempotency-Key": replayKey },
      data: { expected_manifest_sha256: second.manifest_sha256 },
    });
    expect(initialRender.status()).toBe(201);
    expect(replayRender.status()).toBe(200);
    expect(replayRender.headers()["idempotent-replay"]).toBe("true");
    const initialRenderBody = (await initialRender.json()) as RenderResponse;
    const replayRenderBody = (await replayRender.json()) as RenderResponse;
    expect(replayRenderBody.id).toBe(initialRenderBody.id);
    expect(replayRenderBody.sha256).toBe(initialRenderBody.sha256);

    const approvalKey = `approval-replay-${randomUUID()}`;
    const occurredAt = new Date().toISOString();
    const approvalPayload = {
      expected_manifest_sha256: third.manifest_sha256,
      reason: "Exact approval replay acceptance",
      occurred_at: occurredAt,
    };
    const initialApproval = await managerA.post(`/api/v1/reports/${third.id}/approve`, {
      headers: { "Idempotency-Key": approvalKey },
      data: approvalPayload,
    });
    const replayApproval = await managerA.post(`/api/v1/reports/${third.id}/approve`, {
      headers: { "Idempotency-Key": approvalKey },
      data: approvalPayload,
    });
    expect(initialApproval.status()).toBe(201);
    expect(replayApproval.status()).toBe(200);
    expect(replayApproval.headers()["idempotent-replay"]).toBe("true");
    expect((await replayApproval.json()).event_id).toBe((await initialApproval.json()).event_id);

    expect((await managerB.get(`/api/v1/reports/${first.id}/outputs`)).status()).toBe(404);
    const foreignRender = firstState.renders[0]!;
    expect((await managerB.get(`/api/v1/reports/${first.id}/renders/${foreignRender.id}`)).status()).toBe(
      404,
    );

    const viewerContext = await browser.newContext({ baseURL: frontendBaseUrl });
    const viewerPage = await viewerContext.newPage();
    await installBrowserCredentials(viewerPage, viewerAToken, organizationA);
    await viewerPage.goto(`/reports/${first.id}`);
    await expect(viewerPage.getByTestId("report-output-panel")).toBeVisible();
    await expect(viewerPage.getByTestId("report-approval-state")).toContainText("superseded");
    await expect(viewerPage.getByTestId("render-xlsx")).toHaveCount(0);
    await expect(viewerPage.getByTestId("report-approval-actions")).toHaveCount(0);
    await expect(viewerPage.getByTestId("download-render-xlsx")).toBeVisible();
    await viewerContext.close();

    expect((await viewerA.get(`/api/v1/reports/${first.id}/outputs`)).status()).toBe(200);
  } finally {
    await engineerA.dispose();
    await managerA.dispose();
    await managerB.dispose();
    await viewerA.dispose();
  }
});
