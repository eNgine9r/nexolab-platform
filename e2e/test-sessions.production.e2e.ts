import { randomUUID } from "node:crypto";
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type APIRequestContext, type Browser, type BrowserContext } from "@playwright/test";

const organizationA = requiredEnvironment("NEXOLAB_SESSIONS_ORGANIZATION_ID");
const organizationB = requiredEnvironment("NEXOLAB_SESSIONS_OTHER_ORGANIZATION_ID");
const viewerToken = requiredEnvironment("NEXOLAB_SESSIONS_VIEWER_TOKEN");
const engineerAToken = requiredEnvironment("NEXOLAB_SESSIONS_ENGINEER_A_TOKEN");
const engineerBToken = requiredEnvironment("NEXOLAB_SESSIONS_ENGINEER_B_TOKEN");
const apiBaseUrl = requiredEnvironment("NEXT_PUBLIC_NEXOLAB_API_BASE_URL");
const evidenceDirectory = process.env.NEXOLAB_SESSIONS_EVIDENCE_DIR ?? "session-acceptance-evidence";
const composeProject = requiredEnvironment("COMPOSE_PROJECT_NAME");
const baseCompose = requiredEnvironment("NEXOLAB_SESSIONS_BASE_COMPOSE");
const acceptanceCompose = requiredEnvironment("NEXOLAB_SESSIONS_ACCEPTANCE_COMPOSE");
const mqttTopic = process.env.MQTT_TOPIC ?? "nexolab/telemetry";

function headers(token: string, organizationId: string, idempotencyKey?: string): Record<string, string> {
  return {
    Authorization: `Bearer ${token}`,
    "X-Organization-ID": organizationId,
    Accept: "application/json",
    "Content-Type": "application/json",
    ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
  };
}

function command(reason: string) {
  return {
    actor_id: "spoofed-browser-actor",
    actor_source: "spoofed-browser-source",
    occurred_at: new Date().toISOString(),
    reason,
  };
}

async function authenticatedContext(
  browser: Browser,
  token: string,
  organizationId: string,
): Promise<BrowserContext> {
  const context = await browser.newContext();
  await context.addInitScript(
    ({ accessToken, organization }) => {
      if (window.location.protocol === "about:") return;
      window.sessionStorage.setItem("nexolab.acceptance.access-token", accessToken);
      window.sessionStorage.setItem("nexolab.acceptance.organization-id", organization);
    },
    { accessToken: token, organization: organizationId },
  );
  return context;
}

async function createSession(
  request: APIRequestContext,
  token: string,
  organizationId: string,
  idempotencyKey: string,
) {
  const response = await request.post(`${apiBaseUrl}/api/v1/sessions`, {
    headers: headers(token, organizationId, idempotencyKey),
    data: {
      session_number: "NXL-SESSION-GATE-001",
      title: "Organization-scoped browser acceptance",
      test_object: "K106",
      node_id: "edge-01",
      customer: "NEXOLAB Acceptance",
      standard: "ISO 23953",
      ...command("Create controlled session"),
    },
  });
  expect(response.status()).toBe(201);
  return (await response.json()) as {
    session: { id: string; organization_id: string; state: string; session_number: string };
    event: { id: string; actor_id: string; actor_source: string };
    replayed: boolean;
  };
}

async function postCommand(
  request: APIRequestContext,
  pathName: string,
  token: string,
  organizationId: string,
  idempotencyKey: string,
  data: Record<string, unknown>,
) {
  return request.post(`${apiBaseUrl}${pathName}`, {
    headers: headers(token, organizationId, idempotencyKey),
    data,
  });
}

function publishTelemetry(value: number): string {
  const eventId = randomUUID();
  const payload = JSON.stringify({
    event_id: eventId,
    node_id: "edge-01",
    captured_at: new Date().toISOString(),
    metric: "temperature.probe",
    value,
    unit: "degC",
    quality: "valid",
    source: "sessions-browser-acceptance",
    equipment_id: "K106",
    channel_id: "106-03",
    alarm: null,
    raw_value: Math.round(value * 10),
    raw_status: 4354,
  });
  execFileSync(
    "docker",
    [
      "compose",
      "--project-name",
      composeProject,
      "--file",
      baseCompose,
      "--file",
      acceptanceCompose,
      "exec",
      "-T",
      "mqtt",
      "mosquitto_pub",
      "-h",
      "127.0.0.1",
      "-t",
      mqttTopic,
      "-m",
      payload,
    ],
    { stdio: "pipe" },
  );
  return eventId;
}

test("enforces organization-scoped authenticated production session workflow", async ({
  browser,
  request,
}) => {
  mkdirSync(evidenceDirectory, { recursive: true });

  const anonymous = await request.get(`${apiBaseUrl}/api/v1/sessions`, {
    headers: { "X-Organization-ID": organizationA },
  });
  expect(anonymous.status()).toBe(401);

  const createKey = "sessions-gate-shared-create-key";
  const createdA = await createSession(request, engineerAToken, organizationA, createKey);
  const replayedA = await createSession(request, engineerAToken, organizationA, createKey);
  const createdB = await createSession(request, engineerBToken, organizationB, createKey);

  expect(createdA.replayed).toBe(false);
  expect(replayedA.replayed).toBe(true);
  expect(replayedA.session.id).toBe(createdA.session.id);
  expect(createdB.session.id).not.toBe(createdA.session.id);
  expect(createdA.session.organization_id).toBe(organizationA);
  expect(createdB.session.organization_id).toBe(organizationB);
  expect(createdA.event.actor_id).toBe("engineer-a-acceptance");
  expect(createdA.event.actor_source).toBe("acceptance-oidc");

  const viewerRead = await request.get(`${apiBaseUrl}/api/v1/sessions/${createdA.session.id}`, {
    headers: headers(viewerToken, organizationA),
  });
  expect(viewerRead.status()).toBe(200);
  const viewerMutation = await request.patch(`${apiBaseUrl}/api/v1/sessions/${createdA.session.id}`, {
    headers: headers(viewerToken, organizationA),
    data: { title: "Viewer must not mutate" },
  });
  expect(viewerMutation.status()).toBe(403);

  const bindings = await postCommand(
    request,
    `/api/v1/sessions/${createdA.session.id}/bindings/production`,
    engineerAToken,
    organizationA,
    "sessions-gate-bindings",
    { ...command("Bind validated production channels"), binding_metadata: { gate: "sessions-browser" } },
  );
  expect(bindings.status()).toBe(201);
  const bindingsBody = await bindings.json();
  expect(bindingsBody.expected_series_count).toBe(34);
  expect(bindingsBody.bindings).toHaveLength(34);

  const limits = await postCommand(
    request,
    `/api/v1/sessions/${createdA.session.id}/limits`,
    engineerAToken,
    organizationA,
    "sessions-gate-limits-v1",
    {
      ...command("Create temperature limits v1"),
      limits: [
        {
          binding_id: null,
          metric: "temperature.probe",
          unit: "degC",
          lower_limit: -5,
          upper_limit: 10,
          hysteresis: 0.5,
          duration_seconds: 60,
          payload: { standard: "ISO 23953" },
        },
      ],
    },
  );
  expect(limits.status()).toBe(201);
  expect((await limits.json()).version).toBe(1);

  for (const [action, key] of [
    ["prepare", "sessions-gate-prepare"],
    ["start", "sessions-gate-start"],
  ] as const) {
    const response = await postCommand(
      request,
      `/api/v1/sessions/${createdA.session.id}/${action}`,
      engineerAToken,
      organizationA,
      key,
      command(`Controlled ${action}`),
    );
    expect(response.status()).toBe(200);
  }

  const stage = await postCommand(
    request,
    `/api/v1/sessions/${createdA.session.id}/stages/advance`,
    engineerAToken,
    organizationA,
    "sessions-gate-stage-0",
    {
      ...command("Begin preparation stage"),
      sequence_index: 0,
      stage_type: "preparation",
      name: "Preparation",
      planned_duration_seconds: 600,
    },
  );
  expect(stage.status()).toBe(201);
  const stageBody = await stage.json();

  const runningEventId = publishTelemetry(4.6);
  await expect
    .poll(async () => {
      const response = await request.get(
        `${apiBaseUrl}/api/v1/sessions/${createdA.session.id}/telemetry/latest?metric=temperature.probe`,
        { headers: headers(engineerAToken, organizationA) },
      );
      if (!response.ok()) return null;
      const body = await response.json();
      return body.items?.find((item: { event_id: string }) => item.event_id === runningEventId) ?? null;
    })
    .toMatchObject({
      event_id: runningEventId,
      session_id: createdA.session.id,
      stage_id: stageBody.stage.id,
    });

  const paused = await postCommand(
    request,
    `/api/v1/sessions/${createdA.session.id}/pause`,
    engineerAToken,
    organizationA,
    "sessions-gate-pause",
    command("Pause workflow while telemetry continues"),
  );
  expect(paused.status()).toBe(200);

  const pausedEventId = publishTelemetry(4.8);
  await expect
    .poll(async () => {
      const response = await request.get(
        `${apiBaseUrl}/api/v1/sessions/${createdA.session.id}/telemetry/history?from=${encodeURIComponent(
          new Date(Date.now() - 5 * 60_000).toISOString(),
        )}&to=${encodeURIComponent(new Date(Date.now() + 60_000).toISOString())}&metric=temperature.probe`,
        { headers: headers(engineerAToken, organizationA) },
      );
      if (!response.ok()) return false;
      const body = await response.json();
      return body.items?.some(
        (item: { event_id: string; session_id: string; stage_id: string }) =>
          item.event_id === pausedEventId &&
          item.session_id === createdA.session.id &&
          item.stage_id === stageBody.stage.id,
      );
    })
    .toBe(true);

  const resumed = await postCommand(
    request,
    `/api/v1/sessions/${createdA.session.id}/resume`,
    engineerAToken,
    organizationA,
    "sessions-gate-resume",
    command("Resume workflow"),
  );
  expect(resumed.status()).toBe(200);

  const completeKey = "sessions-gate-complete";
  const completed = await postCommand(
    request,
    `/api/v1/sessions/${createdA.session.id}/complete`,
    engineerAToken,
    organizationA,
    completeKey,
    command("Complete controlled session"),
  );
  expect(completed.status()).toBe(200);
  expect((await completed.json()).session.state).toBe("completed");
  const completedReplay = await postCommand(
    request,
    `/api/v1/sessions/${createdA.session.id}/complete`,
    engineerAToken,
    organizationA,
    completeKey,
    command("Complete controlled session"),
  );
  expect(completedReplay.status()).toBe(200);
  expect((await completedReplay.json()).replayed).toBe(true);

  const immutablePatch = await request.patch(`${apiBaseUrl}/api/v1/sessions/${createdA.session.id}`, {
    headers: headers(engineerAToken, organizationA),
    data: { title: "Must remain immutable" },
  });
  expect(immutablePatch.status()).toBe(409);
  expect((await immutablePatch.json()).detail.code).toBe("session_immutable");

  const foreignRead = await request.get(`${apiBaseUrl}/api/v1/sessions/${createdA.session.id}`, {
    headers: headers(engineerBToken, organizationB),
  });
  const missingRead = await request.get(`${apiBaseUrl}/api/v1/sessions/${randomUUID()}`, {
    headers: headers(engineerBToken, organizationB),
  });
  expect(foreignRead.status()).toBe(404);
  expect(missingRead.status()).toBe(404);
  expect((await foreignRead.json()).detail.code).toBe("session_not_found");

  const auditResponse = await request.get(
    `${apiBaseUrl}/api/v1/sessions/${createdA.session.id}/audit?limit=200`,
    {
      headers: headers(engineerAToken, organizationA),
    },
  );
  expect(auditResponse.status()).toBe(200);
  const audit = await auditResponse.json();
  expect(audit.items.length).toBeGreaterThanOrEqual(8);
  expect(audit.items.every((item: { actor_id: string }) => item.actor_id === "engineer-a-acceptance")).toBe(
    true,
  );

  const engineerContext = await authenticatedContext(browser, engineerAToken, organizationA);
  const page = await engineerContext.newPage();
  try {
    await page.goto("/sessions", { waitUntil: "domcontentloaded" });
    await expect(page.getByText("NXL-SESSION-GATE-001", { exact: true })).toBeVisible();
    await page.getByText("NXL-SESSION-GATE-001", { exact: true }).click();
    await expect(page.getByText("Immutable view", { exact: true })).toBeVisible();
    await expect(page.getByText("Organization-scoped browser acceptance", { exact: true })).toBeVisible();
    await page.screenshot({
      path: path.join(evidenceDirectory, "completed-session-immutable.png"),
      fullPage: true,
    });
  } finally {
    await engineerContext.close();
  }

  const archived = await postCommand(
    request,
    `/api/v1/sessions/${createdA.session.id}/archive`,
    engineerAToken,
    organizationA,
    "sessions-gate-archive",
    command("Archive accepted session"),
  );
  expect(archived.status()).toBe(200);
  expect((await archived.json()).session.state).toBe("archived");

  writeFileSync(
    path.join(evidenceDirectory, "test-sessions-acceptance-summary.json"),
    `${JSON.stringify(
      {
        anonymousStatus: 401,
        viewerMutationStatus: 403,
        organizationA,
        organizationB,
        repeatedSessionNumber: createdA.session.session_number,
        independentSessionIds: [createdA.session.id, createdB.session.id],
        createReplay: replayedA.replayed,
        productionBindings: bindingsBody.expected_series_count,
        activeLimitVersion: 1,
        stageId: stageBody.stage.id,
        telemetryAttributedWhileRunning: runningEventId,
        telemetryAttributedWhilePaused: pausedEventId,
        completedImmutableStatus: immutablePatch.status(),
        foreignIdentifierStatus: foreignRead.status(),
        verifiedAuditActor: "engineer-a-acceptance",
        finalState: "archived",
      },
      null,
      2,
    )}\n`,
  );
});

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for test sessions acceptance`);
  return value;
}
