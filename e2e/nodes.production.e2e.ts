import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

const frontendBaseUrl = process.env.NEXOLAB_NODES_BASE_URL ?? "http://127.0.0.1:3106";
const apiBaseUrl = process.env.NEXOLAB_NODES_API_BASE_URL ?? "http://127.0.0.1:8086";
const composeProject = required("NEXOLAB_NODES_COMPOSE_PROJECT");
const organizationA = required("NEXOLAB_NODES_ORGANIZATION_A");
const organizationB = required("NEXOLAB_NODES_ORGANIZATION_B");
const managerAToken = required("NEXOLAB_NODES_MANAGER_A_TOKEN");
const managerBToken = required("NEXOLAB_NODES_MANAGER_B_TOKEN");
const engineerAToken = required("NEXOLAB_NODES_ENGINEER_A_TOKEN");
const viewerAToken = required("NEXOLAB_NODES_VIEWER_A_TOKEN");
const catalogNodeId = "edge-01";
const fixtureRunId = randomUUID().slice(0, 8);
const primaryNodeId = `acceptance-edge-01-${fixtureRunId}`;
const secondaryNodeId = `acceptance-edge-02-${fixtureRunId}`;

const composeArguments = [
  "--project-name",
  composeProject,
  "-f",
  "infrastructure/compose/compose.central.yaml",
  "-f",
  "infrastructure/compose/compose.browser-acceptance.yaml",
];

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

type NodeHealth = {
  event_id: string;
  node_sequence: number;
  health: "healthy" | "degraded";
  queue_depth: number;
  last_error: string | null;
};

type NodeStatus = {
  event_id: string;
  node_sequence: number;
  status: "online" | "offline";
  graceful: boolean;
};

type OperationalState = {
  node_id: string;
  availability: "online" | "offline" | "stale" | "unknown";
  degraded_reason: string | null;
  latest_health: NodeHealth | null;
  latest_status: NodeStatus | null;
};

type OperationalPayload = Record<string, boolean | number | string | null>;

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

function nodeTopic(nodeId: string, stream: "health" | "status"): string {
  return `nexolab/v1/${organizationA}/${nodeId}/${stream}`;
}

function runCompose(arguments_: string[], allowFailure = false): string {
  const result = spawnSync("docker", ["compose", ...composeArguments, ...arguments_], {
    cwd: process.cwd(),
    encoding: "utf8",
    env: process.env,
  });
  if (!allowFailure && result.status !== 0) {
    throw new Error(`docker compose ${arguments_.join(" ")} failed with ${result.status}:\n${result.stderr}`);
  }
  return result.stdout;
}

function publishOperationalEvent(
  nodeId: string,
  stream: "health" | "status",
  payload: OperationalPayload,
  retain = false,
): void {
  const arguments_ = [
    "exec",
    "-T",
    "mqtt",
    "mosquitto_pub",
    "-h",
    "127.0.0.1",
    "-p",
    "1883",
    "-q",
    "1",
    "-t",
    nodeTopic(nodeId, stream),
    "-m",
    JSON.stringify(payload),
  ];
  if (retain) arguments_.push("-r");
  runCompose(arguments_);
}

function retainedOperationalEvent(nodeId: string, stream: "health" | "status"): OperationalPayload {
  const output = runCompose([
    "exec",
    "-T",
    "mqtt",
    "mosquitto_sub",
    "-h",
    "127.0.0.1",
    "-p",
    "1883",
    "-q",
    "1",
    "-C",
    "1",
    "-W",
    "5",
    "-t",
    nodeTopic(nodeId, stream),
  ]);
  return JSON.parse(output.trim()) as OperationalPayload;
}

function triggerLastWill(nodeId: string, payload: OperationalPayload): void {
  const python = String.raw`
import os
import sys
import threading
import paho.mqtt.client as mqtt

connected = threading.Event()
client = mqtt.Client(
    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    client_id="nexolab-edge-02-lwt-acceptance",
    protocol=mqtt.MQTTv311,
)
client.will_set(sys.argv[1], sys.argv[2], qos=1, retain=True)
client.on_connect = lambda *_args: connected.set()
client.connect("mqtt", 1883, keepalive=10)
client.loop_start()
if not connected.wait(5):
    raise SystemExit(72)
os._exit(73)
`;
  runCompose(
    [
      "exec",
      "-T",
      "telemetry-service",
      "python",
      "-c",
      python,
      nodeTopic(nodeId, "status"),
      JSON.stringify(payload),
    ],
    true,
  );
}

async function waitForOperationalState(
  context: APIRequestContext,
  nodeId: string,
  predicate: (state: OperationalState) => boolean,
): Promise<OperationalState> {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const response = await context.get(`/api/v1/nodes/${nodeId}/operational-state`);
    if (response.status() === 200) {
      const state = (await response.json()) as OperationalState;
      if (predicate(state)) return state;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Operational state for ${nodeId} did not reach the expected condition.`);
}

function statusPayload(
  nodeId: string,
  sequence: number,
  status: "online" | "offline",
  graceful: boolean,
  reason: string,
): OperationalPayload {
  return {
    schema_version: 1,
    event_id: randomUUID(),
    node_id: nodeId,
    captured_at: new Date().toISOString(),
    node_sequence: sequence,
    status,
    reason,
    software_version: "0.15.0-acceptance",
    graceful,
  };
}

function healthPayload(
  nodeId: string,
  sequence: number,
  health: "healthy" | "degraded",
  queueDepth: number,
  lastError: string | null,
): OperationalPayload {
  const timestamp = new Date().toISOString();
  return {
    schema_version: 1,
    event_id: randomUUID(),
    node_id: nodeId,
    captured_at: timestamp,
    node_sequence: sequence,
    health,
    uptime_seconds: sequence * 30,
    queue_depth: queueDepth,
    samples_total: sequence * 12,
    software_version: "0.15.0-acceptance",
    device_mode: "simulator",
    last_sample_at: timestamp,
    last_publish_at: timestamp,
    last_error: lastError,
  };
}

test("multi-node registry persists MQTT health, retained LWT status, RBAC and isolation", async ({
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

    await managerPage.getByTestId("node-id-input").fill(primaryNodeId);
    await managerPage.getByTestId("node-name-input").fill("Primary simulated edge");
    await managerPage.getByTestId("provision-node").click();
    await expect(managerPage.getByTestId("one-time-node-secret")).toBeVisible();
    const firstSecret = await managerPage.getByTestId("one-time-node-secret").locator("code").innerText();
    expect(firstSecret).toMatch(/^nxl_node_/);
    await expect(managerPage.getByTestId(`node-row-${primaryNodeId}`)).toBeVisible();
    await expect(managerPage.getByTestId("node-detail")).toContainText("generation 1");

    await managerPage.getByTestId("activate-node").click();
    await expect(managerPage.getByTestId("node-detail")).toContainText("Активний");

    const edgeOneOnline = statusPayload(primaryNodeId, 1, "online", true, "simulated device agent connected");
    const edgeOneHealthy = healthPayload(primaryNodeId, 1, "healthy", 0, null);
    const edgeOneDegraded = healthPayload(primaryNodeId, 2, "degraded", 12, "offline queue backlog");
    publishOperationalEvent(primaryNodeId, "status", edgeOneOnline, true);
    publishOperationalEvent(primaryNodeId, "health", edgeOneHealthy);
    publishOperationalEvent(primaryNodeId, "health", edgeOneHealthy);
    publishOperationalEvent(primaryNodeId, "health", edgeOneDegraded);

    const edgeOneState = await waitForOperationalState(
      managerA,
      primaryNodeId,
      (state) =>
        state.availability === "online" &&
        state.latest_health?.node_sequence === 2 &&
        state.degraded_reason === "offline queue backlog",
    );
    expect(edgeOneState.latest_status?.node_sequence).toBe(1);
    expect(retainedOperationalEvent(primaryNodeId, "status").event_id).toBe(edgeOneOnline.event_id);

    const edgeOneHealthHistory = await managerA.get(`/api/v1/nodes/${primaryNodeId}/health-history?limit=10`);
    expect(edgeOneHealthHistory.status()).toBe(200);
    expect(((await edgeOneHealthHistory.json()) as NodeHealth[]).map((row) => row.node_sequence)).toEqual([
      2, 1,
    ]);

    await managerPage.getByLabel("Оновити вузли").click();
    await expect(managerPage.getByTestId(`node-row-availability-${primaryNodeId}`)).toHaveText("online");
    await expect(managerPage.getByTestId("node-availability")).toHaveText("Online");
    await expect(managerPage.getByTestId("node-operational-state")).toContainText("12 events");
    await expect(managerPage.getByTestId("node-degraded-reason")).toContainText("offline queue backlog");

    await managerPage.getByTestId("rotate-node-credential").click();
    await expect(managerPage.getByTestId("one-time-node-secret")).toContainText("generation 2");
    const rotatedSecret = await managerPage.getByTestId("one-time-node-secret").locator("code").innerText();
    expect(rotatedSecret).toMatch(/^nxl_node_/);
    expect(rotatedSecret).not.toBe(firstSecret);
    await expect(managerPage.getByTestId("node-detail")).toContainText("generation 2");
    await managerContext.close();

    const edgeOne = await managerA.get(`/api/v1/nodes/${primaryNodeId}`);
    expect(edgeOne.status()).toBe(200);
    const edgeOneBody = (await edgeOne.json()) as NodeResponse;
    expect(edgeOneBody.organization_id).toBe(organizationA);
    expect(edgeOneBody.state).toBe("active");
    expect(edgeOneBody.current_credential?.generation).toBe(2);

    const replayKey = `nodes-${secondaryNodeId}-${randomUUID()}`;
    const edgeTwoPayload = {
      node_id: secondaryNodeId,
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

    const activateEdgeTwo = await managerA.post(`/api/v1/nodes/${secondaryNodeId}/activate`, {
      data: { reason: "Simulated commissioning complete" },
    });
    expect(activateEdgeTwo.status()).toBe(200);
    expect(((await activateEdgeTwo.json()) as NodeResponse).state).toBe("active");

    const edgeTwoOnline = statusPayload(
      secondaryNodeId,
      1,
      "online",
      true,
      "simulated device agent connected",
    );
    const edgeTwoHealth = healthPayload(secondaryNodeId, 1, "healthy", 0, null);
    const edgeTwoWill = statusPayload(secondaryNodeId, 2, "offline", false, "mqtt last will");
    publishOperationalEvent(secondaryNodeId, "status", edgeTwoOnline, true);
    publishOperationalEvent(secondaryNodeId, "health", edgeTwoHealth);
    await waitForOperationalState(
      managerA,
      secondaryNodeId,
      (state) => state.availability === "online" && state.latest_health?.node_sequence === 1,
    );

    triggerLastWill(secondaryNodeId, edgeTwoWill);
    const edgeTwoOfflineState = await waitForOperationalState(
      managerA,
      secondaryNodeId,
      (state) =>
        state.availability === "offline" &&
        state.latest_status?.node_sequence === 2 &&
        state.latest_status.graceful === false,
    );
    expect(edgeTwoOfflineState.latest_status?.event_id).toBe(edgeTwoWill.event_id);
    expect(retainedOperationalEvent(secondaryNodeId, "status").event_id).toBe(edgeTwoWill.event_id);

    const viewerList = await viewerA.get("/api/v1/nodes");
    expect(viewerList.status()).toBe(200);
    expect(((await viewerList.json()) as NodeResponse[]).map((node) => node.node_id).sort()).toEqual(
      [catalogNodeId, primaryNodeId, secondaryNodeId].sort(),
    );

    const viewerContext = await browser.newContext({ baseURL: frontendBaseUrl });
    const viewerPage = await viewerContext.newPage();
    await installBrowserCredentials(viewerPage, viewerAToken, organizationA);
    await viewerPage.goto("/nodes");
    await expect(viewerPage.getByTestId("nodes-workspace")).toBeVisible();
    await expect(viewerPage.getByTestId("node-provision-panel")).toHaveCount(0);
    await expect(viewerPage.getByText("Поточна роль має read-only доступ.")).toBeVisible();
    await viewerPage.getByTestId(`node-row-${secondaryNodeId}`).click();
    await expect(viewerPage.getByTestId(`node-row-availability-${secondaryNodeId}`)).toHaveText("offline");
    await expect(viewerPage.getByTestId("node-availability")).toHaveText("Offline");
    await expect(viewerPage.getByTestId("node-actions")).toHaveCount(0);
    await viewerContext.close();

    const foreignList = await managerB.get("/api/v1/nodes");
    expect(foreignList.status()).toBe(200);
    expect((await foreignList.json()) as NodeResponse[]).toEqual([]);
    expect((await managerB.get(`/api/v1/nodes/${primaryNodeId}`)).status()).toBe(404);
    expect((await managerB.get(`/api/v1/nodes/${primaryNodeId}/operational-state`)).status()).toBe(404);

    const suspendEdgeTwo = await managerA.post(`/api/v1/nodes/${secondaryNodeId}/suspend`, {
      data: { reason: "Simulated maintenance" },
    });
    expect(suspendEdgeTwo.status()).toBe(200);
    expect(((await suspendEdgeTwo.json()) as NodeResponse).state).toBe("suspended");

    const revokeEdgeTwo = await managerA.post(`/api/v1/nodes/${secondaryNodeId}/revoke`, {
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
