import { createHmac } from "node:crypto";

import { expect, test, type Browser, type BrowserContext, type Route } from "@playwright/test";

const organizationId = requiredEnvironment("NEXOLAB_DASHBOARD_ORGANIZATION_ID");
const viewerToken = requiredEnvironment("NEXOLAB_DASHBOARD_VIEWER_TOKEN");
const jwtSecret = requiredEnvironment("AUTH_JWT_PUBLIC_KEY");
const jwtIssuer = requiredEnvironment("AUTH_JWT_ISSUER");
const jwtAudience = requiredEnvironment("AUTH_JWT_AUDIENCE");
const engineerToken = acceptanceToken("equipment-engineer-acceptance", "Equipment Engineer Acceptance");

const candidateId = "60600000-0000-4000-8000-000000000001";
const scanId = "60610000-0000-4000-8000-000000000001";

type CandidateLifecycle = "new" | "reviewed" | "adopted";

type ObservedDiscoveryRequest = {
  method: string;
  pathname: string;
  authorization: boolean;
  organization: string | null;
  body: unknown;
  ifMatch: string | null;
};

async function authenticatedContext(browser: Browser, accessToken: string): Promise<BrowserContext> {
  const context = await browser.newContext();
  await context.addInitScript(
    ({ token, organization }) => {
      if (window.location.protocol === "about:") return;
      window.sessionStorage.setItem("nexolab.acceptance.access-token", token);
      window.sessionStorage.setItem("nexolab.acceptance.organization-id", organization);
    },
    { token: accessToken, organization: organizationId },
  );
  return context;
}

function acceptanceToken(subject: string, name: string): string {
  const now = Math.floor(Date.now() / 1000);
  const encode = (value: unknown) => Buffer.from(JSON.stringify(value)).toString("base64url");
  const header = encode({ alg: "HS256", typ: "JWT" });
  const payload = encode({
    sub: subject,
    email: `${subject}@example.test`,
    name,
    iss: jwtIssuer,
    aud: jwtAudience,
    iat: now,
    exp: now + 1800,
  });
  const signature = createHmac("sha256", jwtSecret).update(`${header}.${payload}`).digest("base64url");
  return `${header}.${payload}.${signature}`;
}

function discoveryFixture() {
  const requests: ObservedDiscoveryRequest[] = [];
  let lifecycle: CandidateLifecycle = "new";
  let version = 1;
  let scanCompleted = false;
  let networkAssetCreated = false;

  const candidate = () => ({
    id: candidateId,
    candidate_key: "ip:192.168.50.2",
    ip_address: "192.168.50.2",
    mac_address: "aa:bb:cc:dd:ee:02",
    hostname: "lab-controller-02",
    source_interface: "eth0",
    source_subnet: "192.168.50.0/30",
    lifecycle,
    present: true,
    first_seen_at: "2026-08-20T06:00:00Z",
    last_seen_at: "2026-08-20T06:01:00Z",
    last_scan_id: scanId,
    linked_equipment_key: null,
    version,
    services: [{ port: 443, transport: "tcp", service: "https", evidence: "connect_succeeded" }],
    evidence: { tcp_connect_only: true, payload_bytes_sent: 0 },
    changed_since_previous_scan: false,
  });

  const scan = (status: "running" | "completed") => ({
    id: scanId,
    status,
    requested_cidrs: ["192.168.50.0/30"],
    requested_ports: [80, 443],
    host_budget: 2,
    probe_budget: 4,
    hosts_considered: status === "completed" ? 2 : 0,
    probes_attempted: status === "completed" ? 4 : 0,
    responsive_hosts: status === "completed" ? 1 : 0,
    duration_ms: status === "completed" ? 18 : 0,
    process_cpu_ms: status === "completed" ? 3 : 0,
    network_connect_attempts: status === "completed" ? 4 : 0,
    network_payload_bytes: 0,
    trigger: "manual",
    new_candidates: status === "completed" ? 1 : 0,
    changed_candidates: 0,
    disappeared_candidates: 0,
    cancel_requested: false,
    requested_by: "equipment-engineer-acceptance",
    started_at: "2026-08-20T06:00:00Z",
    completed_at: status === "completed" ? "2026-08-20T06:01:00Z" : null,
    error_code: null,
    error_message: null,
  });

  const overview = () => ({
    policy: {
      enabled: true,
      allowed_cidrs: ["192.168.50.0/30"],
      allowed_ports: [80, 443],
      max_hosts: 16,
      max_ports: 3,
      connect_timeout_seconds: 0.2,
      concurrency: 4,
      schedule_interval_seconds: 0,
      probe_mode: "tcp-connect-only",
      payload_bytes_sent_per_probe: 0,
    },
    active_scan: null,
    last_scan: scanCompleted ? scan("completed") : null,
    candidates: [candidate()],
    network_assets: networkAssetCreated
      ? [
          {
            id: "60620000-0000-4000-8000-000000000001",
            asset_key: "network:60600000-0000-4000-8000-000000000001",
            display_name: "LAB network device",
            ip_address: "192.168.50.2",
            mac_address: "aa:bb:cc:dd:ee:02",
            manufacturer: null,
            model: null,
            source_candidate_id: candidateId,
            status: "active",
            version: 1,
            created_by: "equipment-engineer-acceptance",
            created_at: "2026-08-20T06:02:00Z",
            updated_at: "2026-08-20T06:02:00Z",
          },
        ]
      : [],
  });

  const handler = async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const headers = request.headers();
    const body = request.postData() ? request.postDataJSON() : null;
    requests.push({
      method: request.method(),
      pathname: url.pathname,
      authorization: headers.authorization?.startsWith("Bearer ") ?? false,
      organization: headers["x-organization-id"] ?? null,
      body,
      ifMatch: headers["if-match"] ?? null,
    });

    if (request.method() === "GET" && url.pathname === "/api/v1/equipment-discovery") {
      await route.fulfill({ status: 200, json: overview() });
      return;
    }
    if (request.method() === "POST" && url.pathname === "/api/v1/equipment-discovery/scans") {
      scanCompleted = true;
      await route.fulfill({ status: 202, json: scan("running") });
      return;
    }
    if (request.method() === "POST" && url.pathname.endsWith("/cancel")) {
      await route.fulfill({ status: 200, json: scan("completed") });
      return;
    }
    if (
      request.method() === "PATCH" &&
      url.pathname === `/api/v1/equipment-discovery/candidates/${candidateId}`
    ) {
      const action = (body as { action?: string } | null)?.action;
      if (action === "review") {
        lifecycle = "reviewed";
        version += 1;
      } else if (action === "adopt") {
        lifecycle = "adopted";
        version += 1;
        networkAssetCreated = true;
      }
      await route.fulfill({
        status: 200,
        headers: { ETag: `W/"equipment-discovery-candidate-v${version}"` },
        json: {
          candidate: candidate(),
          network_asset: networkAssetCreated ? overview().network_assets[0] : null,
        },
      });
      return;
    }
    await route.abort("failed");
  };

  return { requests, handler };
}

test("viewer sees discovery evidence without automatic scan or mutation path", async ({ browser }) => {
  const context = await authenticatedContext(browser, viewerToken);
  const page = await context.newPage();
  const fixture = discoveryFixture();
  await page.route("**/api/v1/equipment-discovery**", fixture.handler);

  await page.goto("/equipment");
  await expect(page.getByRole("heading", { name: "Нові пристрої" })).toBeVisible();
  await expect(page.getByText("lab-controller-02")).toBeVisible();
  await expect(page.getByText(/TCP 443 · https · connect succeeded/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Запустити scan" })).toBeDisabled();
  await expect(page.getByText("Доступ лише для перегляду discovery evidence.")).toBeVisible();
  await page.waitForTimeout(500);

  expect(fixture.requests.filter((item) => item.method !== "GET")).toEqual([]);
  expect(fixture.requests.every((item) => item.authorization && item.organization === organizationId)).toBe(
    true,
  );
  await context.close();
});

test("engineer explicitly scans configured scope and adopts only an administrative network asset", async ({
  browser,
}) => {
  const context = await authenticatedContext(browser, engineerToken);
  const page = await context.newPage();
  const fixture = discoveryFixture();
  await page.route("**/api/v1/equipment-discovery**", fixture.handler);
  const nonDiscoveryMutations: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (
      request.method() !== "GET" &&
      !url.pathname.startsWith("/api/v1/equipment-discovery") &&
      (url.pathname.includes("acquisition") ||
        url.pathname.includes("device-agent") ||
        url.pathname.includes("modbus"))
    ) {
      nonDiscoveryMutations.push(`${request.method()} ${url.pathname}`);
    }
  });

  await page.goto("/equipment");
  await expect(page.getByRole("heading", { name: "Нові пристрої" })).toBeVisible();
  await page.getByRole("button", { name: "Запустити scan" }).click();
  await expect
    .poll(
      () =>
        fixture.requests.filter((item) => item.pathname.endsWith("/scans") && item.method === "POST").length,
    )
    .toBe(1);

  const scanRequest = fixture.requests.find(
    (item) => item.pathname.endsWith("/scans") && item.method === "POST",
  );
  expect(scanRequest?.body).toEqual({ cidrs: ["192.168.50.0/30"], ports: [80, 443] });

  await page.getByRole("button", { name: "Переглянуто" }).click();
  await expect(page.locator("span").filter({ hasText: /^Переглянуто$/ })).toBeVisible();
  const reviewRequest = fixture.requests.find(
    (item) => item.method === "PATCH" && (item.body as { action?: string } | null)?.action === "review",
  );
  expect(reviewRequest?.ifMatch).toBe('W/"equipment-discovery-candidate-v1"');

  const adoptInput = page.getByLabel("Adopted asset name for 192.168.50.2");
  await adoptInput.fill("LAB network device");
  await page.getByRole("button", { name: "Adopt" }).click();
  await expect(page.getByText("Adopted", { exact: true })).toBeVisible();
  const adoptRequest = fixture.requests.find(
    (item) => item.method === "PATCH" && (item.body as { action?: string } | null)?.action === "adopt",
  );
  expect(adoptRequest?.ifMatch).toBe('W/"equipment-discovery-candidate-v2"');
  expect(adoptRequest?.body).toEqual({ action: "adopt", display_name: "LAB network device" });
  expect(nonDiscoveryMutations).toEqual([]);
  await context.close();
});

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for Equipment discovery acceptance`);
  return value;
}
