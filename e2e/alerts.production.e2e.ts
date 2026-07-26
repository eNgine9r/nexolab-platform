import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

const apiBaseUrl = process.env.NEXOLAB_ALERTS_API_BASE_URL ?? "http://127.0.0.1:8083";
const mqttHost = process.env.NEXOLAB_ALERTS_MQTT_HOST ?? "127.0.0.1";
const mqttPort = process.env.NEXOLAB_ALERTS_MQTT_PORT ?? "1885";
const mqttTopic = process.env.NEXOLAB_ALERTS_MQTT_TOPIC ?? "nexolab/telemetry";
const organizationA = required("NEXOLAB_ALERTS_ORGANIZATION_A");
const organizationB = required("NEXOLAB_ALERTS_ORGANIZATION_B");
const managerAToken = required("NEXOLAB_ALERTS_MANAGER_A_TOKEN");
const managerBToken = required("NEXOLAB_ALERTS_MANAGER_B_TOKEN");
const viewerAToken = required("NEXOLAB_ALERTS_VIEWER_A_TOKEN");

interface AlertRuleResponse {
  id: string;
  organization_id: string;
  current_version: number;
  version: {
    id: string;
    version: number;
  };
}

interface AlertResponse {
  id: string;
  organization_id: string;
  rule_id: string;
  state: "active" | "acknowledged" | "resolved" | "closed";
  node_id: string;
  equipment_id: string;
  channel_id: string;
  metric: string;
  maximum_deviation: number;
}

interface AlertPageResponse {
  items: AlertResponse[];
  count: number;
}

interface TransitionResponse {
  id: string;
  event_type: string;
  actor_id: string;
  actor_source: string;
  idempotency_key: string;
}

interface TransitionPageResponse {
  items: TransitionResponse[];
  count: number;
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
        : {
            Accept: "application/json",
          },
  });
}

function rulePayload(name: string): Record<string, unknown> {
  return {
    name,
    description: "Controlled production alert acceptance",
    severity: "critical",
    node_id: "edge-01",
    equipment_id: "K106",
    channel_id: "106-03",
    metric: "temperature.probe",
    condition: "threshold_high",
    trigger_threshold: 8,
    clear_threshold: 7,
    minimum_duration_seconds: 2,
    clear_duration_seconds: 2,
    debounce_seconds: 0,
    cooldown_seconds: 1,
    configuration: {
      acceptance: true,
      standard: "ISO 23953",
    },
  };
}

function publishTelemetry(
  capturedAt: Date,
  value: number,
  eventId: string = randomUUID(),
): { eventId: string; payload: Record<string, unknown> } {
  const payload = {
    event_id: eventId,
    node_id: "edge-01",
    captured_at: capturedAt.toISOString(),
    metric: "temperature.probe",
    value,
    unit: "degC",
    quality: "valid",
    source: "alerts-browser-acceptance",
    equipment_id: "K106",
    channel_id: "106-03",
    organization_id: organizationA,
  };
  execFileSync(
    "mosquitto_pub",
    ["-h", mqttHost, "-p", mqttPort, "-t", mqttTopic, "-m", JSON.stringify(payload), "-q", "1"],
    { stdio: "inherit" },
  );
  return { eventId, payload };
}

async function expectAlertCount(
  context: APIRequestContext,
  path: string,
  expected: number,
  ruleId?: string,
): Promise<AlertPageResponse> {
  let body: AlertPageResponse | null = null;
  let matchingItems: AlertPageResponse["items"] = [];
  await expect
    .poll(
      async () => {
        const response = await context.get(path);
        expect(response.status()).toBe(200);
        body = (await response.json()) as AlertPageResponse;
        matchingItems = ruleId ? body.items.filter((item) => item.rule_id === ruleId) : body.items;
        return matchingItems.length;
      },
      { timeout: 30_000 },
    )
    .toBe(expected);
  if (!body) throw new Error(`No response body returned for ${path}`);
  return { items: matchingItems, count: matchingItems.length };
}

async function expectAlertState(
  context: APIRequestContext,
  alertId: string,
  expected: AlertResponse["state"],
): Promise<AlertResponse> {
  let alert: AlertResponse | null = null;
  await expect
    .poll(
      async () => {
        const response = await context.get(`/api/v1/alerts/${alertId}`);
        expect(response.status()).toBe(200);
        alert = (await response.json()) as AlertResponse;
        return alert.state;
      },
      { timeout: 30_000 },
    )
    .toBe(expected);
  if (!alert) throw new Error(`Alert ${alertId} was not returned`);
  return alert;
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
    },
    { token: accessToken, organization: organizationId },
  );
}

test("production alerts enforce deterministic lifecycle on Next.js, FastAPI, PostgreSQL and MQTT", async ({
  page,
}) => {
  const anonymous = await apiContext();
  const managerA = await apiContext(managerAToken, organizationA);
  const managerB = await apiContext(managerBToken, organizationB);
  const viewerA = await apiContext(viewerAToken, organizationA);

  try {
    const anonymousResponse = await anonymous.get("/api/v1/alerts/latest", {
      headers: { "X-Organization-ID": organizationA },
    });
    expect(anonymousResponse.status()).toBe(401);

    const ruleName = `Acceptance high temperature ${randomUUID()}`;
    const createA = await managerA.post("/api/v1/alerts/rules", {
      data: rulePayload(ruleName),
    });
    expect(createA.status()).toBe(201);
    const ruleA = (await createA.json()) as AlertRuleResponse;
    expect(ruleA.organization_id).toBe(organizationA);
    expect(ruleA.current_version).toBe(1);

    const createB = await managerB.post("/api/v1/alerts/rules", {
      data: rulePayload(ruleName),
    });
    expect(createB.status()).toBe(201);
    const ruleB = (await createB.json()) as AlertRuleResponse;
    expect(ruleB.organization_id).toBe(organizationB);
    expect(ruleB.id).not.toBe(ruleA.id);

    const viewerCreate = await viewerA.post("/api/v1/alerts/rules", {
      data: rulePayload(`Viewer denied ${randomUUID()}`),
    });
    expect(viewerCreate.status()).toBe(403);

    const foreignRule = await managerB.get(`/api/v1/alerts/rules/${ruleA.id}`);
    expect(foreignRule.status()).toBe(404);

    const revised = await managerA.put(`/api/v1/alerts/rules/${ruleA.id}`, {
      data: {
        ...rulePayload(ruleName),
        enabled: true,
      },
    });
    expect(revised.status()).toBe(200);
    const revisedRule = (await revised.json()) as AlertRuleResponse;
    expect(revisedRule.current_version).toBe(2);
    expect(revisedRule.version.id).not.toBe(ruleA.version.id);

    const base = new Date();
    publishTelemetry(base, 8.6);
    publishTelemetry(new Date(base.getTime() + 1_000), 7.5);
    await expectAlertCount(managerA, "/api/v1/alerts/latest", 0, ruleA.id);

    publishTelemetry(new Date(base.getTime() + 10_000), 8.7);
    const sustained = publishTelemetry(new Date(base.getTime() + 13_000), 9.4);
    const latest = await expectAlertCount(managerA, "/api/v1/alerts/latest", 1, ruleA.id);
    const alert = latest.items[0];
    expect(alert.organization_id).toBe(organizationA);
    expect(alert.node_id).toBe("edge-01");
    expect(alert.equipment_id).toBe("K106");
    expect(alert.channel_id).toBe("106-03");
    expect(alert.metric).toBe("temperature.probe");
    expect(alert.maximum_deviation).toBeCloseTo(1.4);

    publishTelemetry(new Date(base.getTime() + 13_000), 9.4, sustained.eventId);
    publishTelemetry(new Date(base.getTime() + 11_000), 12.5);
    await expectAlertCount(managerA, "/api/v1/alerts/latest", 1, ruleA.id);

    const foreignAlert = await managerB.get(`/api/v1/alerts/${alert.id}`);
    expect(foreignAlert.status()).toBe(404);

    const viewerList = await viewerA.get("/api/v1/alerts/latest");
    expect(viewerList.status()).toBe(200);
    const viewerAcknowledge = await viewerA.post(`/api/v1/alerts/${alert.id}/acknowledge`, {
      headers: { "Idempotency-Key": `viewer-denied-${randomUUID()}` },
      data: { reason: "Viewer must not mutate alerts" },
    });
    expect(viewerAcknowledge.status()).toBe(403);

    await installBrowserCredentials(page, managerAToken, organizationA);
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.goto("/alerts", { waitUntil: "networkidle" });
    await expect(page.getByTestId("alerts-workspace")).toBeVisible();
    await expect(page.getByText("K106 / 106-03")).toBeVisible();
    await expect(page.getByTestId("alert-detail").getByText("9,4 degC")).toBeVisible();
    expect(page.url()).not.toContain(managerAToken);

    await page
      .getByPlaceholder("Що перевірено оператором…")
      .fill("Operator inspected K106 and confirmed the excursion");
    await page.getByTestId("acknowledge-alert").click();
    await expect(page.getByTestId("alert-detail").getByText("Підтверджена")).toBeVisible();
    await expectAlertState(managerA, alert.id, "acknowledged");

    const transitionsAfterAck = await managerA.get(`/api/v1/alerts/${alert.id}/transitions`);
    expect(transitionsAfterAck.status()).toBe(200);
    const transitionPage = (await transitionsAfterAck.json()) as TransitionPageResponse;
    const acknowledgedTransition = transitionPage.items.find(
      (item) => item.event_type === "alert_acknowledged",
    );
    expect(acknowledgedTransition?.actor_id).toBe("manager-a-alerts-acceptance");
    expect(acknowledgedTransition?.actor_source).toBe("alerts-acceptance");

    publishTelemetry(new Date(base.getTime() + 14_000), 7.5);
    await expectAlertState(managerA, alert.id, "acknowledged");
    publishTelemetry(new Date(base.getTime() + 15_000), 6.9);
    publishTelemetry(new Date(base.getTime() + 18_000), 6.8);
    await expectAlertState(managerA, alert.id, "resolved");

    await expect(page.getByTestId("close-alert")).toBeVisible({ timeout: 20_000 });
    await page
      .getByPlaceholder("Чому alert можна контрольовано закрити…")
      .fill("Stable clear condition verified against the configured hysteresis");
    let closeIdempotencyKey: string | null = null;
    page.on("request", (requestDetails) => {
      if (
        requestDetails.method() === "POST" &&
        requestDetails.url().endsWith(`/api/v1/alerts/${alert.id}/close`)
      ) {
        closeIdempotencyKey = requestDetails.headers()["idempotency-key"] ?? null;
      }
    });
    await page.getByTestId("close-alert").click();
    await expectAlertState(managerA, alert.id, "closed");
    await expect(page.getByTestId("alert-detail").getByText("Закрита")).toBeVisible();
    expect(closeIdempotencyKey).not.toBeNull();

    const closeReplay = await managerA.post(`/api/v1/alerts/${alert.id}/close`, {
      headers: { "Idempotency-Key": closeIdempotencyKey ?? "missing" },
      data: {
        reason: "Stable clear condition verified against the configured hysteresis",
        occurred_at: new Date().toISOString(),
      },
    });
    expect(closeReplay.status()).toBe(200);
    expect((await closeReplay.json()).replayed).toBe(true);

    await expectAlertCount(managerA, "/api/v1/alerts/latest", 0, ruleA.id);
    const history = await expectAlertCount(managerA, "/api/v1/alerts/history", 1, ruleA.id);
    expect(history.items[0].id).toBe(alert.id);

    const evidenceResponse = await managerA.get(`/api/v1/alerts/${alert.id}/evidence`);
    expect(evidenceResponse.status()).toBe(200);
    const evidence = (await evidenceResponse.json()) as { count: number };
    expect(evidence.count).toBeGreaterThanOrEqual(2);

    const finalTransitionsResponse = await managerA.get(`/api/v1/alerts/${alert.id}/transitions`);
    const finalTransitions = (await finalTransitionsResponse.json()) as TransitionPageResponse;
    expect(finalTransitions.items.filter((item) => item.event_type === "alert_triggered")).toHaveLength(1);
    expect(finalTransitions.items.filter((item) => item.event_type === "alert_resolved")).toHaveLength(1);
    expect(finalTransitions.items.filter((item) => item.event_type === "alert_closed")).toHaveLength(1);
    expect(pageErrors).toEqual([]);

    await page.screenshot({
      path: "test-results-alerts/alerts-lifecycle.png",
      fullPage: true,
    });
  } finally {
    await anonymous.dispose();
    await managerA.dispose();
    await managerB.dispose();
    await viewerA.dispose();
  }
});
