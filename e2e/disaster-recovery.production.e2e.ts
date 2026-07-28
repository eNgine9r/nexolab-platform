import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

const apiBaseUrl = process.env.NEXOLAB_DR_BROWSER_API_BASE_URL ?? "http://127.0.0.1:8098";
const organizationId =
  process.env.NEXOLAB_DR_BROWSER_ORGANIZATION_ID ?? "00000000-0000-0000-0000-000000000099";
const evidenceDirectory =
  process.env.NEXOLAB_DR_BROWSER_EVIDENCE_DIR ?? "test-results-disaster-recovery-browser";

function authHeaders(): Record<string, string> {
  return {
    Authorization: "Bearer disaster-recovery-browser-acceptance",
    "X-Organization-ID": organizationId,
    Accept: "application/json",
  };
}

async function apiContext(): Promise<APIRequestContext> {
  return request.newContext({
    baseURL: apiBaseUrl,
    extraHTTPHeaders: authHeaders(),
  });
}

async function installBrowserCredentials(page: Page): Promise<void> {
  await page.addInitScript(
    ({ token, organization }) => {
      if (window.location.protocol === "about:") return;
      window.sessionStorage.setItem("nexolab.acceptance.access-token", token);
      window.sessionStorage.setItem("nexolab.acceptance.organization-id", organization);
      window.localStorage.setItem("nexolab.selectedOrganizationId", organization);
    },
    {
      token: "disaster-recovery-browser-acceptance",
      organization: organizationId,
    },
  );
}

test("restored nodes, reports and refrigeration state remain operator-visible", async ({ browser }) => {
  const api = await apiContext();
  const context = await browser.newContext();
  const page = await context.newPage();
  await installBrowserCredentials(page);

  try {
    const nodesResponse = await api.get("/api/v1/nodes");
    expect(nodesResponse.status()).toBe(200);
    const nodesPayload = (await nodesResponse.json()) as Array<{
      node_id: string;
      display_name: string;
      state: string;
    }>;
    expect(nodesPayload).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ node_id: "edge-01", display_name: "DR Edge 01", state: "active" }),
        expect.objectContaining({ node_id: "edge-02", display_name: "DR Edge 02", state: "suspended" }),
      ]),
    );

    await page.goto("/nodes");
    await expect(page.getByTestId("nodes-workspace")).toBeVisible();
    await expect(page.getByTestId("node-row-edge-01")).toContainText("DR Edge 01");
    await expect(page.getByTestId("node-row-edge-02")).toContainText("DR Edge 02");
    await page.screenshot({ path: `${evidenceDirectory}/01-restored-nodes.png`, fullPage: true });

    const reportsResponse = await api.get("/api/v1/reports?limit=20");
    expect(reportsResponse.status()).toBe(200);
    const reportsPayload = (await reportsResponse.json()) as {
      items: Array<{
        id: string;
        session_id: string;
        version: number;
        session_state: string;
        artifacts: Array<{ name: string; sha256: string }>;
      }>;
    };
    expect(reportsPayload.items).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: "60000000-0000-0000-0000-000000000099",
          session_id: "40000000-0000-0000-0000-000000000099",
          version: 1,
          session_state: "completed",
          artifacts: expect.arrayContaining([
            expect.objectContaining({
              name: "protocol-proof.bin",
              sha256: "8891e05dd3204700089d03971479cfd3725e5127ba5530fa5785d0f2824cd0dd",
            }),
          ]),
        }),
      ]),
    );

    await page.goto("/reports");
    const reportDetail = page.getByTestId("report-detail");
    await expect(page.getByTestId("reports-workspace")).toBeVisible();
    await expect(
      reportDetail.getByRole("heading", {
        name: "Session 40000000-0000-0000-0000-000000000099",
      }),
    ).toBeVisible();
    await expect(reportDetail).toContainText("protocol-proof.bin");
    await page.screenshot({ path: `${evidenceDirectory}/02-restored-reports.png`, fullPage: true });

    const draftResponse = await api.get("/api/v1/equipment/showcase-106-01/layout/draft");
    expect(draftResponse.status()).toBe(200);
    expect(draftResponse.headers()["etag"]).toBe('W/"layout-draft-v1"');
    const draft = (await draftResponse.json()) as {
      equipment_id: string;
      version: number;
      image: { original_filename: string; media_type: string; content_url: string };
      placements: Array<{ sensor_id: string; x: number; y: number }>;
    };
    expect(draft).toMatchObject({
      equipment_id: "showcase-106-01",
      version: 1,
      image: {
        original_filename: "dr-restored-showcase.png",
        media_type: "image/png",
      },
    });
    expect(draft.placements).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ sensor_id: "sensor-1", x: 0.25, y: 0.35 }),
        expect.objectContaining({ sensor_id: "sensor-2", x: 0.75, y: 0.65 }),
      ]),
    );

    const imageResponse = await api.get(draft.image.content_url, {
      headers: { Accept: "image/png" },
    });
    expect(imageResponse.status()).toBe(200);
    expect(imageResponse.headers()["content-type"]).toContain("image/png");
    expect((await imageResponse.body()).byteLength).toBeGreaterThan(0);

    await page.goto("/refrigeration/showcase-106-01");
    await expect(page.getByRole("heading", { name: "Вітрина №106-01" })).toBeVisible();
    await expect(page.getByText("Чернетка v1 · PostgreSQL")).toBeVisible();
    await expect(page.getByText("Ревізія r1")).toBeVisible();
    await expect(page.getByText("dr-restored-showcase.png").first()).toBeVisible();
    await expect(page.getByText("Завантаження production-схеми, публікації та історії…")).toBeHidden();
    await page.screenshot({
      path: `${evidenceDirectory}/03-restored-refrigeration.png`,
      fullPage: true,
    });
  } finally {
    await page.close();
    await context.close();
    await api.dispose();
  }
});
