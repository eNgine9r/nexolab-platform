import { randomUUID } from "node:crypto";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

const frontendBaseUrl = process.env.NEXOLAB_NODES_BASE_URL ?? "http://127.0.0.1:3106";
const apiBaseUrl = process.env.NEXOLAB_NODES_API_BASE_URL ?? "http://127.0.0.1:8086";
const organizationA = required("NEXOLAB_NODES_ORGANIZATION_A");
const organizationB = required("NEXOLAB_NODES_ORGANIZATION_B");
const managerAToken = required("NEXOLAB_NODES_MANAGER_A_TOKEN");
const managerBToken = required("NEXOLAB_NODES_MANAGER_B_TOKEN");
const engineerAToken = required("NEXOLAB_NODES_ENGINEER_A_TOKEN");
const viewerAToken = required("NEXOLAB_NODES_VIEWER_A_TOKEN");

type Credential = {
  id: string;
  generation: number;
  secret_fingerprint: string;
};

type NodeResponse = {
  id: string;
  organization_id: string;
  node_id: string;
  display_name: string;
  state: "pending" | "active" | "suspended" | "revoked";
  current_credential: Credential | null;
};

type ProvisionResponse = {
  node: NodeResponse;
  credential: Credential;
  provisioning_secret: string | null;
  replayed: boolean;
};

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

test("multi-node registry preserves one-time credentials, RBAC and organization isolation", async ({
  browser,
}) => {
  const managerA = await apiContext(managerAToken, organizationA);
  const managerB = await apiContext(managerBToken, organizationB);
  const engineerA = await apiContext(engineerAToken, organizationA);
  const viewerA = await apiContext(viewerAToken, organizationA);

  try {
    const managerContext = await browser.newContext({ baseURL: frontendBaseUrl });
    const managerPage = await managerContext.newPage();
    await installBrowserCredentials(managerPage, managerAToken, organizationA);
    await managerPage.goto("/nodes");
    await expect(managerPage.getByTestId("nodes-workspace")).toBeVisible();
    await expect(managerPage.getByTestId("node-provision-panel")).toBeVisible();

    await managerPage.getByTestId("node-id-input").fill("edge-01");
    await managerPage.getByTestId("node-name-input").fill("Primary simulated edge");
    await managerPage.getByTestId("provision-node").click();
    await expect(managerPage.getByTestId("one-time-node-secret")).toBeVisible();
    const firstSecret = await managerPage.getByTestId("one-time-node-secret").locator("code").innerText();
    expect(firstSecret).toMatch(/^nxl_node_/);
    await expect(managerPage.getByTestId("node-row-edge-01")).toBeVisible();
    await expect(managerPage.getByTestId("node-detail")).toContainText("generation 1");

    await managerPage.getByTestId("activate-node").click();
    await expect(managerPage.getByTestId("node-detail")).toContainText("Активний");

    await managerPage.getByTestId("rotate-node-credential").click();
    await expect(managerPage.getByTestId("one-time-node-secret")).toContainText("generation 2");
    const rotatedSecret = await managerPage
      .getByTestId("one-time-node-secret")
      .locator("code")
      .innerText();
    expect(rotatedSecret).toMatch(/^nxl_node_/);
    expect(rotatedSecret).not.toBe(firstSecret);
    await expect(managerPage.getByTestId("node-detail")).toContainText("generation 2");
    await managerContext.close();

    const edgeOne = await managerA.get("/api/v1/nodes/edge-01");
    expect(edgeOne.status()).toBe(200);
    const edgeOneBody = (await edgeOne.json()) as NodeResponse;
    expect(edgeOneBody.organization_id).toBe(organizationA);
    expect(edgeOneBody.state).toBe("active");
    expect(edgeOneBody.current_credential?.generation).toBe(2);

    const replayKey = `nodes-edge-02-${randomUUID()}`;
    const edgeTwoPayload = {
      node_id: "edge-02",
      display_name: "Secondary simulated edge",
      clock_warning_ms: 30_000,
      clock_critical_ms: 120_000,
    };
    const firstProvision = await managerA.post("/api/v1/nodes", {
      headers: { "Idempotency-Key": replayKey },
      data: edgeTwoPayload,
    });
    expect(firstProvision.status()).toBe(201);
    const firstProvisionBody = (await firstProvision.json()) as ProvisionResponse;
    expect(firstProvisionBody.provisioning_secret).toMatch(/^nxl_node_/);
    expect(firstProvisionBody.credential.generation).toBe(1);

    const replayProvision = await managerA.post("/api/v1/nodes", {
      headers: { "Idempotency-Key": replayKey },
      data: edgeTwoPayload,
    });
    expect(replayProvision.status()).toBe(200);
    expect(replayProvision.headers()["idempotent-replay"]).toBe("true");
    const replayBody = (await replayProvision.json()) as ProvisionResponse;
    expect(replayBody.node.id).toBe(firstProvisionBody.node.id);
    expect(replayBody.credential.id).toBe(firstProvisionBody.credential.id);
    expect(replayBody.provisioning_secret).toBeNull();
    expect(replayBody.replayed).toBe(true);

    const engineerDenied = await engineerA.post("/api/v1/nodes", {
      headers: { "Idempotency-Key": `engineer-denied-${randomUUID()}` },
      data: {
        node_id: "edge-engineer",
        display_name: "Engineer must not provision",
      },
    });
    expect(engineerDenied.status()).toBe(403);

    const viewerList = await viewerA.get("/api/v1/nodes");
    expect(viewerList.status()).toBe(200);
    expect(((await viewerList.json()) as NodeResponse[]).map((node) => node.node_id).sort()).toEqual([
      "edge-01",
      "edge-02",
    ]);

    const viewerContext = await browser.newContext({ baseURL: frontendBaseUrl });
    const viewerPage = await viewerContext.newPage();
    await installBrowserCredentials(viewerPage, viewerAToken, organizationA);
    await viewerPage.goto("/nodes");
    await expect(viewerPage.getByTestId("nodes-workspace")).toBeVisible();
    await expect(viewerPage.getByTestId("node-provision-panel")).toHaveCount(0);
    await expect(viewerPage.getByText("Поточна роль має read-only доступ.")).toBeVisible();
    await expect(viewerPage.getByTestId("node-actions")).toHaveCount(0);
    await viewerContext.close();

    const foreignList = await managerB.get("/api/v1/nodes");
    expect(foreignList.status()).toBe(200);
    expect((await foreignList.json()) as NodeResponse[]).toEqual([]);
    expect((await managerB.get("/api/v1/nodes/edge-01")).status()).toBe(404);

    const activateEdgeTwo = await managerA.post("/api/v1/nodes/edge-02/activate", {
      data: { reason: "Simulated commissioning complete" },
    });
    expect(activateEdgeTwo.status()).toBe(200);
    expect(((await activateEdgeTwo.json()) as NodeResponse).state).toBe("active");

    const suspendEdgeTwo = await managerA.post("/api/v1/nodes/edge-02/suspend", {
      data: { reason: "Simulated maintenance" },
    });
    expect(suspendEdgeTwo.status()).toBe(200);
    expect(((await suspendEdgeTwo.json()) as NodeResponse).state).toBe("suspended");

    const revokeEdgeTwo = await managerA.post("/api/v1/nodes/edge-02/revoke", {
      data: { reason: "Simulated node retirement" },
    });
    expect(revokeEdgeTwo.status()).toBe(200);
    const revoked = (await revokeEdgeTwo.json()) as NodeResponse;
    expect(revoked.state).toBe("revoked");
    expect(revoked.current_credential).toBeNull();
  } finally {
    await managerA.dispose();
    await managerB.dispose();
    await engineerA.dispose();
    await viewerA.dispose();
  }
});
