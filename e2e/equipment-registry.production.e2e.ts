import { execFileSync } from "node:child_process";
import { createHmac } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";

const organizationId = requiredEnvironment("NEXOLAB_DASHBOARD_ORGANIZATION_ID");
const viewerToken = requiredEnvironment("NEXOLAB_DASHBOARD_VIEWER_TOKEN");
const jwtSecret = requiredEnvironment("AUTH_JWT_PUBLIC_KEY");
const jwtIssuer = requiredEnvironment("AUTH_JWT_ISSUER");
const jwtAudience = requiredEnvironment("AUTH_JWT_AUDIENCE");
const engineerToken = acceptanceToken("equipment-engineer-acceptance", "Equipment Engineer Acceptance");
const evidenceDirectory = process.env.NEXOLAB_DASHBOARD_EVIDENCE_DIR ?? "dashboard-acceptance-evidence";
const composeProject = requiredEnvironment("COMPOSE_PROJECT_NAME");
const baseCompose = requiredEnvironment("NEXOLAB_DASHBOARD_BASE_COMPOSE");
const acceptanceCompose = requiredEnvironment("NEXOLAB_DASHBOARD_ACCEPTANCE_COMPOSE");
const postgresDatabase = process.env.POSTGRES_DB?.trim() || "nexolab";
const postgresUser = process.env.POSTGRES_USER?.trim() || "nexolab";

const nodeRecordId = "66000000-0000-4000-8000-000000000001";
const busId = "66100000-0000-4000-8000-000000000001";
const chamberAId = "66200000-0000-4000-8000-000000000001";
const chamberBId = "66200000-0000-4000-8000-000000000002";
const activeEquipmentId = "66600000-0000-4000-8000-000000000001";

let expectedAssetCount = 0;
const minimumFocusedFixtureCount = 190;

type ObservedRegistryRequest = {
  method: string;
  pathname: string;
  authorization: boolean;
  organization: string | null;
};

async function authenticatedContext(browser: Browser, accessToken = viewerToken): Promise<BrowserContext> {
  const context = await browser.newContext();
  await context.addInitScript(
    ({ accessToken, organization }) => {
      if (window.location.protocol === "about:") return;
      window.sessionStorage.setItem("nexolab.acceptance.access-token", accessToken);
      window.sessionStorage.setItem("nexolab.acceptance.organization-id", organization);
    },
    { accessToken, organization: organizationId },
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

function observeRegistryRequests(page: Page): ObservedRegistryRequest[] {
  const requests: ObservedRegistryRequest[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (
      !url.pathname.startsWith("/api/v1/equipment") &&
      !url.pathname.startsWith("/api/v1/climate-chambers")
    ) {
      return;
    }
    const headers = request.headers();
    requests.push({
      method: request.method(),
      pathname: url.pathname,
      authorization: headers.authorization?.startsWith("Bearer ") ?? false,
      organization: headers["x-organization-id"] ?? null,
    });
  });
  return requests;
}

function composeBaseArguments(): string[] {
  return ["compose", "--project-name", composeProject, "--file", baseCompose, "--file", acceptanceCompose];
}

function composeExec(service: string, args: string[], input?: string): string {
  return execFileSync("docker", [...composeBaseArguments(), "exec", "-T", service, ...args], {
    input,
    encoding: "utf8",
    env: process.env,
    stdio: ["pipe", "pipe", "pipe"],
  });
}

function seedEquipmentRegistryFixtures(): void {
  mkdirSync(evidenceDirectory, { recursive: true });
  const sql = `
INSERT INTO security_identities (id, provider, subject, email, display_name, is_active)
VALUES (
  'cccccccc-cccc-cccc-cccc-ccccccccccc5', 'acceptance-oidc',
  'equipment-engineer-acceptance', 'equipment-engineer-acceptance@example.test',
  'Equipment Engineer Acceptance', true
)
ON CONFLICT (provider, subject) DO UPDATE SET
  email = EXCLUDED.email, display_name = EXCLUDED.display_name, is_active = true;

INSERT INTO security_organization_memberships (id, organization_id, identity_id, is_active)
VALUES (
  'dddddddd-dddd-dddd-dddd-ddddddddddd5', :'organization_id',
  'cccccccc-cccc-cccc-cccc-ccccccccccc5', true
)
ON CONFLICT (organization_id, identity_id) DO UPDATE SET is_active = true;

INSERT INTO security_membership_roles (membership_id, role, assigned_by)
VALUES ('dddddddd-dddd-dddd-dddd-ddddddddddd5', 'engineer', 'equipment-registry-acceptance')
ON CONFLICT (membership_id, role) DO NOTHING;

INSERT INTO security_membership_permissions (membership_id, permission, assigned_by)
VALUES
  ('dddddddd-dddd-dddd-dddd-ddddddddddd5', 'dashboard.read', 'equipment-registry-acceptance'),
  ('dddddddd-dddd-dddd-dddd-ddddddddddd5', 'equipment.manage', 'equipment-registry-acceptance')
ON CONFLICT (membership_id, permission) DO NOTHING;

INSERT INTO central_nodes (
  id, organization_id, node_id, display_name, state, state_reason,
  clock_warning_ms, clock_critical_ms, last_seen_at, last_clock_offset_ms,
  clock_status, clock_observed_at, created_by, created_at, updated_at
)
VALUES (
  '${nodeRecordId}', :'organization_id', 'registry-edge-01', 'Registry Edge Node',
  'active', 'equipment registry browser fixture', 30000, 120000,
  CURRENT_TIMESTAMP, 0, 'ok', CURRENT_TIMESTAMP,
  'equipment-registry-acceptance', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
)
ON CONFLICT (organization_id, node_id) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  state = EXCLUDED.state,
  last_seen_at = EXCLUDED.last_seen_at,
  updated_at = EXCLUDED.updated_at;

INSERT INTO measurement_buses (
  id, organization_id, node_id, bus_key, display_name, protocol, port,
  baudrate, data_bits, parity, stop_bits, status, version,
  created_by, updated_by, created_at, updated_at
)
VALUES (
  '${busId}', :'organization_id', 'registry-edge-01', 'registry-rs485-01',
  'Registry RS-485', 'modbus_rtu', '/dev/ttyREGISTRY', 9600, 8, 'N', 1,
  'active', 1, 'equipment-registry-acceptance', 'equipment-registry-acceptance',
  CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
)
ON CONFLICT (organization_id, bus_key) DO NOTHING;

INSERT INTO climate_chambers (
  id, organization_id, bus_id, code, name, display_order, status, version,
  created_by, updated_by, created_at, updated_at
)
VALUES
  (
    '${chamberAId}', :'organization_id', '${busId}', 'REG-A', 'Registry Chamber A',
    901, 'active', 1, 'equipment-registry-acceptance', 'equipment-registry-acceptance',
    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
  ),
  (
    '${chamberBId}', :'organization_id', '${busId}', 'REG-B', 'Registry Chamber B',
    902, 'active', 1, 'equipment-registry-acceptance', 'equipment-registry-acceptance',
    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
  )
ON CONFLICT (organization_id, code) DO NOTHING;

INSERT INTO measurement_devices (
  id, organization_id, climate_chamber_id, bus_id, business_key, device_type,
  manufacturer, model, unit_id, display_name, designation, connection_status,
  status, measured_parameters, created_at, updated_at
)
VALUES
  (
    '66300000-0000-4000-8000-000000000001', :'organization_id', '${chamberAId}', '${busId}',
    'reg-xjp:11', 'temperature_controller', 'NEXOLAB', 'XJP60D', 11,
    'Registry Controller Connected', NULL, 'connected', 'active',
    '[{"metric":"temperature","unit":"degC"}]'::json, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
  ),
  (
    '66300000-0000-4000-8000-000000000002', :'organization_id', '${chamberAId}', '${busId}',
    'reg-le01mp:12', 'energy_meter', 'TOMZN', 'LE-01MP', 12,
    'Registry Energy Meter', 'E1', 'disconnected', 'active',
    '[{"metric":"active_power","unit":"W"}]'::json, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
  ),
  (
    '66300000-0000-4000-8000-000000000003', :'organization_id', '${chamberAId}', '${busId}',
    'reg-xjp:13', 'temperature_controller', 'Omega', 'XJP60D', 13,
    'Registry Controller Unknown', NULL, 'unknown', 'active',
    '[{"metric":"temperature","unit":"degC"}]'::json, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
  ),
  (
    '66300000-0000-4000-8000-000000000004', :'organization_id', '${chamberBId}', '${busId}',
    'reg-xjp:21', 'temperature_controller', 'NEXOLAB', 'XJP60D', 21,
    'Registry Failed Chamber Controller', NULL, 'connected', 'active',
    '[{"metric":"temperature","unit":"degC"}]'::json, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
  ),
  (
    '66300000-0000-4000-8000-000000000005', :'organization_id', '${chamberAId}', '${busId}',
    'met-edit-device:18', 'temperature_controller', 'EDITFIX', 'XJP60D', 18,
    'Metadata Edit Device', 'EDIT-18', 'unknown', 'active',
    '[{"metric":"temperature","unit":"degC"}]'::json, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
  )
ON CONFLICT (organization_id, business_key) DO NOTHING;

INSERT INTO measurement_channels (
  id, organization_id, climate_chamber_id, bus_id, device_id,
  channel_id, source_channel_id, channel_number, logical_sensor_number,
  display_name, physical_sensor_count, metric_type, unit, status,
  created_at, updated_at
)
VALUES
  (
    '66400000-0000-4000-8000-000000000001', :'organization_id', '${chamberAId}', '${busId}',
    '66300000-0000-4000-8000-000000000001', 'registry-temp-01', 'registry-source-01',
    1, 901, 'Registry Channel Current', 1, 'temperature', 'degC', 'active',
    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
  ),
  (
    '66400000-0000-4000-8000-000000000002', :'organization_id', '${chamberAId}', '${busId}',
    '66300000-0000-4000-8000-000000000001', 'registry-temp-02', 'registry-source-02',
    2, 902, 'Registry Channel Due', 1, 'temperature', 'degC', 'active',
    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
  ),
  (
    '66400000-0000-4000-8000-000000000003', :'organization_id', '${chamberAId}', '${busId}',
    '66300000-0000-4000-8000-000000000001', 'registry-temp-03', 'registry-source-03',
    3, 903, 'Registry Channel Expired', 1, 'temperature', 'degC', 'active',
    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
  ),
  (
    '66400000-0000-4000-8000-000000000004', :'organization_id', '${chamberAId}', '${busId}',
    '66300000-0000-4000-8000-000000000001', 'registry-temp-04', 'registry-source-04',
    4, 904, 'Registry Channel Untracked', 1, 'temperature', 'degC', 'active',
    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
  ),
  (
    '66400000-0000-4000-8000-000000000005', :'organization_id', '${chamberAId}', '${busId}',
    '66300000-0000-4000-8000-000000000001', 'registry-temp-edit', 'registry-source-edit',
    5, 905, 'Registry Channel Metadata Edit', 1, 'temperature', 'degC', 'active',
    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
  )
ON CONFLICT (organization_id, channel_id) DO NOTHING;

INSERT INTO physical_sensors (
  id, organization_id, climate_chamber_id, channel_id, sensor_position,
  inventory_number, serial_number, calibration_status, status, created_at, updated_at
)
VALUES
  (
    '66500000-0000-4000-8000-000000000001', :'organization_id', '${chamberAId}',
    '66400000-0000-4000-8000-000000000001', 'A', 'MET-SENSOR-CUR', 'MET-SN-CUR',
    'current', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
  ),
  (
    '66500000-0000-4000-8000-000000000002', :'organization_id', '${chamberAId}',
    '66400000-0000-4000-8000-000000000002', 'A', 'MET-SENSOR-DUE', 'MET-SN-DUE',
    'due', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
  ),
  (
    '66500000-0000-4000-8000-000000000003', :'organization_id', '${chamberAId}',
    '66400000-0000-4000-8000-000000000003', 'A', 'MET-SENSOR-EXP', 'MET-SN-EXP',
    'expired', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
  ),
  (
    '66500000-0000-4000-8000-000000000004', :'organization_id', '${chamberAId}',
    '66400000-0000-4000-8000-000000000004', 'A', 'MET-SENSOR-UNT', NULL,
    'untracked', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
  ),
  (
    '66500000-0000-4000-8000-000000000005', :'organization_id', '${chamberAId}',
    '66400000-0000-4000-8000-000000000005', 'B', 'MET-SENSOR-EDIT', 'MET-SN-EDIT',
    'untracked', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
  )
ON CONFLICT (organization_id, inventory_number) DO NOTHING;

INSERT INTO refrigeration_equipment (
  id, organization_id, code, name, location, laboratory, zone, node_id,
  climate_chamber_id, equipment_type, manufacturer, model, serial_number,
  temperature_class, installed_at, serviced_at, lifecycle_status, status,
  average_temperature_c, min_temperature_c, max_temperature_c,
  online_sensors, total_sensors, active_alarms, last_seen_at, version,
  created_by, created_at, updated_at, deleted_by, deleted_at
)
VALUES
  (
    '${activeEquipmentId}', :'organization_id', 'REG-REF-ACTIVE', 'Registry Active Showcase',
    'Registry Lab · Zone A', 'Registry Lab', 'Zone A', 'registry-edge-01', '${chamberAId}',
    'Холодильна вітрина', 'NEXOLAB', 'REG-ACTIVE', 'REG-SN-ACTIVE', '3M1',
    DATE '2026-01-10', DATE '2026-07-20', 'active', 'normal', 3.2, 2.8, 3.7,
    4, 4, 0, CURRENT_TIMESTAMP, 1, 'equipment-registry-acceptance',
    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL, NULL
  ),
  (
    '66600000-0000-4000-8000-000000000002', :'organization_id',
    'REG-REF-MAINT', 'Registry Maintenance Showcase', 'Registry Lab · Zone B',
    'Registry Lab', 'Zone B', 'registry-edge-01', '${chamberAId}',
    'Холодильна вітрина', 'NEXOLAB', 'REG-MAINT', 'REG-SN-MAINT', '3M1',
    DATE '2026-01-11', DATE '2026-07-21', 'maintenance', 'warning', 4.1, 3.5, 4.8,
    3, 4, 1, CURRENT_TIMESTAMP, 1, 'equipment-registry-acceptance',
    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL, NULL
  ),
  (
    '66600000-0000-4000-8000-000000000003', :'organization_id',
    'REG-REF-RETIRED', 'Registry Retired Showcase', 'Registry Lab · Archive',
    'Registry Lab', 'Archive', 'registry-edge-01', '${chamberBId}',
    'Холодильна вітрина', 'NEXOLAB', 'REG-RETIRED', 'REG-SN-RETIRED', '3M2',
    DATE '2025-01-12', DATE '2026-06-22', 'retired', 'offline', 0, 0, 0,
    0, 4, 0, NULL, 1, 'equipment-registry-acceptance',
    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL, NULL
  )
ON CONFLICT (organization_id, code) DO NOTHING;

INSERT INTO refrigeration_equipment (
  id, organization_id, code, name, location, laboratory, zone, node_id,
  climate_chamber_id, equipment_type, manufacturer, model, serial_number,
  temperature_class, installed_at, serviced_at, lifecycle_status, status,
  average_temperature_c, min_temperature_c, max_temperature_c,
  online_sensors, total_sensors, active_alarms, last_seen_at, version,
  created_by, created_at, updated_at, deleted_by, deleted_at
)
SELECT
  ('66700000-0000-4000-8000-' || lpad(series::text, 12, '0'))::uuid,
  :'organization_id',
  'ZZ-SCALE-' || lpad(series::text, 3, '0'),
  'Scale fixture ' || lpad(series::text, 3, '0'),
  'Registry Scale Lab · Zone ' || ((series - 1) % 12 + 1),
  'Registry Scale Lab',
  'Zone ' || ((series - 1) % 12 + 1),
  'registry-edge-01',
  '${chamberAId}',
  'Холодильна вітрина',
  CASE WHEN series % 3 = 0 THEN 'NEXOLAB' WHEN series % 3 = 1 THEN 'Danfoss' ELSE 'Copeland' END,
  'SCALE-' || lpad(series::text, 3, '0'),
  'SCALE-SN-' || lpad(series::text, 3, '0'),
  '3M1',
  DATE '2026-01-01', DATE '2026-07-01',
  'active',
  CASE WHEN series % 17 = 0 THEN 'warning' ELSE 'normal' END,
  4.0, 2.0, 6.0, 2, 2,
  CASE WHEN series % 17 = 0 THEN 1 ELSE 0 END,
  CURRENT_TIMESTAMP, 1, 'equipment-registry-scale-acceptance',
  CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL, NULL
FROM generate_series(1, 180) AS series
ON CONFLICT (organization_id, code) DO NOTHING;
`;

  composeExec(
    "postgres",
    [
      "psql",
      "-U",
      postgresUser,
      "-d",
      postgresDatabase,
      "-v",
      "ON_ERROR_STOP=1",
      "-v",
      `organization_id=${organizationId}`,
    ],
    sql,
  );
}

function cleanupEquipmentRegistryScaleFixtures(): void {
  composeExec(
    "postgres",
    [
      "psql",
      "-U",
      postgresUser,
      "-d",
      postgresDatabase,
      "-v",
      "ON_ERROR_STOP=1",
      "-v",
      `organization_id=${organizationId}`,
    ],
    "DELETE FROM refrigeration_equipment WHERE organization_id = :'organization_id' AND created_by = 'equipment-registry-scale-acceptance';\n",
  );
}

function databaseScalar(sql: string): string {
  return composeExec("postgres", [
    "psql",
    "-U",
    postgresUser,
    "-d",
    postgresDatabase,
    "-v",
    "ON_ERROR_STOP=1",
    "-tA",
    "-c",
    sql,
  ]).trim();
}

function writeDatabaseEvidence(): void {
  const output = composeExec("postgres", [
    "psql",
    "-U",
    postgresUser,
    "-d",
    postgresDatabase,
    "-v",
    "ON_ERROR_STOP=1",
    "-c",
    [
      "SELECT code, lifecycle_status, status, climate_chamber_id",
      "FROM refrigeration_equipment",
      `WHERE organization_id = '${organizationId}' AND code LIKE 'REG-REF-%'`,
      "ORDER BY code;",
      "SELECT business_key, display_name, manufacturer, model, unit_id, connection_status, version, climate_chamber_id",
      "FROM measurement_devices",
      `WHERE organization_id = '${organizationId}' AND business_key LIKE 'reg-%'`,
      "ORDER BY business_key;",
      "SELECT inventory_number, serial_number, sensor_position, calibration_status, status, version, climate_chamber_id",
      "FROM physical_sensors",
      `WHERE organization_id = '${organizationId}' AND inventory_number LIKE 'MET-SENSOR-%'`,
      "ORDER BY inventory_number;",
      "SELECT actor_subject, action, entity_type, entity_id, reason, before_snapshot, after_snapshot",
      "FROM security_audit_events",
      `WHERE organization_id = '${organizationId}' AND actor_subject = 'equipment-engineer-acceptance'`,
      "ORDER BY occurred_at;",
    ].join(" "),
  ]);
  writeFileSync(path.join(evidenceDirectory, "equipment-registry-database-state.txt"), output);
}

test("renders and navigates the authenticated Equipment and metrology registry", async ({ browser }) => {
  seedEquipmentRegistryFixtures();
  const context = await authenticatedContext(browser);
  const page = await context.newPage();
  const requests = observeRegistryRequests(page);
  const acquisitionMutations: string[] = [];
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (request.method() !== "GET" && pathname.includes("acquisition-registry")) {
      acquisitionMutations.push(`${request.method()} ${pathname}`);
    }
  });
  let injectedFailureCount = 0;
  let chamberARequestPending = false;
  let releaseChamberA!: () => void;
  const chamberAGate = new Promise<void>((resolve) => {
    releaseChamberA = resolve;
  });

  await page.route(`**/api/v1/climate-chambers/${chamberAId}/equipment`, async (route) => {
    if (route.request().method() !== "GET") {
      await route.continue();
      return;
    }
    chamberARequestPending = true;
    await chamberAGate;
    chamberARequestPending = false;
    await route.continue();
  });

  await page.route(`**/api/v1/climate-chambers/${chamberBId}/equipment`, async (route) => {
    if (route.request().method() !== "GET") {
      await route.continue();
      return;
    }
    injectedFailureCount += 1;
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        detail: {
          code: "equipment_registry_acceptance_partial_failure",
          message: "Injected chamber registry failure",
        },
      }),
    });
  });

  try {
    await test.step("render all supported asset and metrology states with one partial failure", async () => {
      await page.goto("/equipment", { waitUntil: "domcontentloaded" });
      await expect(page.getByText("Viewer Acceptance", { exact: true })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Обладнання та метрологія" })).toBeVisible();
      await expect.poll(() => chamberARequestPending).toBe(true);
      const progressiveSearch = page.getByPlaceholder(
        "Код, inventory, business key, модель або серійний номер",
      );
      await progressiveSearch.fill("REG-REF-ACTIVE");
      await expect(page.getByText("REG-REF-ACTIVE", { exact: true }).first()).toBeVisible();
      await expect(page.getByText(/Каталоги \d+\/\d+/, { exact: true })).toBeVisible();
      await progressiveSearch.fill("");
      releaseChamberA();
      await expect.poll(() => chamberARequestPending).toBe(false);
      await expect(page.getByText(/Каталоги \d+\/\d+/, { exact: true })).toHaveCount(0);
      const resultCount = page.getByText(/Показано \d+ із \d+/, { exact: true });
      await expect(resultCount).toBeVisible();
      await expect
        .poll(
          async () => {
            const countText = await resultCount.textContent();
            const countMatch = countText?.match(/Показано (\d+) із (\d+)/);
            if (!countMatch) return 0;
            const visibleCount = Number(countMatch[1]);
            expectedAssetCount = Number(countMatch[2]);
            return visibleCount === expectedAssetCount ? expectedAssetCount : 0;
          },
          { message: "Wait for the complete organization-wide registry total" },
        )
        .toBeGreaterThanOrEqual(minimumFocusedFixtureCount);

      const fixtureSearch = page.getByPlaceholder("Код, inventory, business key, модель або серійний номер");
      for (const identifier of [
        "REG-REF-ACTIVE",
        "REG-REF-MAINT",
        "REG-REF-RETIRED",
        "reg-xjp:11",
        "reg-le01mp:12",
        "reg-xjp:13",
        "MET-SENSOR-CUR",
        "MET-SENSOR-DUE",
        "MET-SENSOR-EXP",
        "MET-SENSOR-UNT",
      ]) {
        await fixtureSearch.fill(identifier);
        await expect(page.getByText(identifier, { exact: true }).first()).toBeVisible();
      }
      await fixtureSearch.fill("");
      await expect(page.getByText("Частина chamber catalog недоступна", { exact: true })).toBeVisible();
      await expect(page.getByText("REG-B · Registry Chamber B:", { exact: true })).toBeVisible();
      expect(injectedFailureCount).toBeGreaterThan(0);

      await expect.poll(() => requests.length).toBeGreaterThanOrEqual(4);
      expect(requests.every((request) => request.authorization)).toBe(true);
      expect(requests.every((request) => request.organization === organizationId)).toBe(true);
      expect(requests.every((request) => request.method === "GET")).toBe(true);
      await expect(page.getByTestId("equipment-registry-table").locator("tbody > tr")).toHaveCount(
        Math.min(expectedAssetCount, 80),
      );
      await expect(page.getByRole("button", { name: /Наступна/ })).toBeEnabled();
    });

    await test.step("persist combined physical-sensor filters through the URL and reload", async () => {
      const search = page.getByPlaceholder("Код, inventory, business key, модель або серійний номер");
      await search.fill("MET-SENSOR-EXP");
      await page.getByLabel("Категорія активу").selectOption("physical-sensor");
      await page.getByLabel("Кліматична камера").selectOption(chamberAId);
      await page.getByRole("combobox", { name: "Статус", exact: true }).selectOption("connected");
      await page.getByLabel("Статус калібрування").selectOption("expired");

      await expect(page.getByText(`Показано 1 із ${expectedAssetCount}`, { exact: true })).toBeVisible();
      await expect(
        page.getByText("MET-SENSOR-EXP", { exact: true }).filter({ visible: true }).first(),
      ).toBeVisible();
      await expect
        .poll(() => {
          const url = new URL(page.url());
          return {
            q: url.searchParams.get("q"),
            category: url.searchParams.get("category"),
            chamber: url.searchParams.get("chamber"),
            status: url.searchParams.get("status"),
            calibration: url.searchParams.get("calibration"),
          };
        })
        .toEqual({
          q: "MET-SENSOR-EXP",
          category: "physical-sensor",
          chamber: chamberAId,
          status: "connected",
          calibration: "expired",
        });

      await page.reload({ waitUntil: "domcontentloaded" });
      await expect(page.getByText(/Каталоги \d+\/\d+/, { exact: true })).toHaveCount(0);
      await expect(search).toHaveValue("MET-SENSOR-EXP");
      await expect(page.getByLabel("Категорія активу")).toHaveValue("physical-sensor");
      await expect(page.getByLabel("Кліматична камера")).toHaveValue(chamberAId);
      await expect(page.getByRole("combobox", { name: "Статус", exact: true })).toHaveValue("connected");
      await expect(page.getByLabel("Статус калібрування")).toHaveValue("expired");
      await expect(page.getByText(`Показано 1 із ${expectedAssetCount}`, { exact: true })).toBeVisible();

      await page.getByRole("button", { name: "Очистити активні фільтри", exact: true }).click();
      await expect
        .poll(() => {
          const url = new URL(page.url());
          return [
            url.searchParams.get("q"),
            url.searchParams.get("category"),
            url.searchParams.get("chamber"),
            url.searchParams.get("status"),
            url.searchParams.get("calibration"),
            url.searchParams.get("risk"),
          ];
        })
        .toEqual([null, null, null, null, null, null]);
      await expect(
        page.getByText(`Показано ${expectedAssetCount} із ${expectedAssetCount}`, { exact: true }),
      ).toBeVisible();
    });

    await test.step("combine manufacturer, device class and connection filters", async () => {
      await page.getByLabel("Категорія активу").selectOption("energy-meter");
      await page.getByRole("combobox", { name: "Виробник", exact: true }).selectOption("TOMZN");
      await page.getByRole("combobox", { name: "Статус", exact: true }).selectOption("disconnected");
      await expect(page.getByText(`Показано 1 із ${expectedAssetCount}`, { exact: true })).toBeVisible();
      await expect(
        page.getByText("reg-le01mp:12", { exact: true }).filter({ visible: true }).first(),
      ).toBeVisible();
      await page.getByRole("button", { name: "Очистити активні фільтри", exact: true }).click();
      await expect(
        page.getByText(`Показано ${expectedAssetCount} із ${expectedAssetCount}`, { exact: true }),
      ).toBeVisible();
    });

    await test.step("persist workspace density, grouping, sorting and visible columns locally", async () => {
      const densityButton = page.getByRole("button", { name: /щільність/ });
      await expect(densityButton).toContainText("Комфортна");
      await densityButton.click();
      await expect(densityButton).toContainText("Компактна");

      await page.getByLabel("Групування реєстру").selectOption("manufacturer");
      await page.getByRole("button", { name: "Сортувати: Виробник / модель" }).click();
      await page.getByRole("button", { name: /Колонки/ }).click();
      await page.getByLabel("Категорія", { exact: true }).uncheck();
      await expect(page.getByRole("columnheader", { name: /Категорія/ })).toHaveCount(0);

      await expect.poll(() => new URL(page.url()).searchParams.get("group")).toBe("manufacturer");
      await expect.poll(() => new URL(page.url()).searchParams.get("sort")).toBe("manufacturer");
      await page.reload({ waitUntil: "domcontentloaded" });
      await expect(page.getByText(/Каталоги \d+\/\d+/, { exact: true })).toHaveCount(0);
      await expect(page.getByLabel("Групування реєстру")).toHaveValue("manufacturer");
      await expect(page.getByRole("button", { name: /щільність/ })).toContainText("Компактна");
      await expect(page.getByRole("columnheader", { name: /Категорія/ })).toHaveCount(0);

      await page.getByRole("button", { name: /^Офлайн/ }).click();
      await expect.poll(() => new URL(page.url()).searchParams.get("risk")).toBe("offline");
      await page
        .getByPlaceholder("Код, inventory, business key, модель або серійний номер")
        .fill("REG-REF-RETIRED");
      await expect(page.getByText("REG-REF-RETIRED", { exact: true }).first()).toBeVisible();
      await page.getByRole("button", { name: "Очистити активні фільтри", exact: true }).click();

      await page.getByLabel("Групування реєстру").selectOption("none");
      await page.getByRole("button", { name: /Колонки/ }).click();
      await page.getByLabel("Категорія", { exact: true }).check();
    });

    await test.step("inspect adjacent assets in a non-blocking desktop drawer with keyboard access", async () => {
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.getByPlaceholder("Код, inventory, business key, модель або серійний номер").fill("REG-REF-");
      const activeRow = page.getByRole("row").filter({ hasText: "REG-REF-ACTIVE" }).first();
      await activeRow.focus();
      await page.keyboard.press("Enter");
      const drawer = page.getByRole("dialog", { name: "Паспорт REG-REF-ACTIVE" });
      await expect(drawer).toBeVisible();
      await expect(page.getByTestId("equipment-registry-table")).toBeVisible();
      const drawerBox = await drawer.boundingBox();
      expect(drawerBox).not.toBeNull();
      expect(drawerBox?.x ?? 0).toBeGreaterThan(700);
      await page.keyboard.press("ArrowDown");
      await expect(page.getByRole("dialog", { name: "Паспорт REG-REF-MAINT" })).toBeVisible();
      await page.getByRole("button", { name: "Закрити паспорт обладнання" }).click();
      await page.getByPlaceholder("Код, inventory, business key, модель або серійний номер").fill("");
    });

    await test.step("remain bounded and overflow-safe at operator desktop widths", async () => {
      for (const viewport of [
        { width: 1440, height: 900 },
        { width: 1920, height: 1080 },
      ]) {
        await page.setViewportSize(viewport);
        const dimensions = await page.evaluate(() => ({
          scrollWidth: document.documentElement.scrollWidth,
          clientWidth: document.documentElement.clientWidth,
        }));
        expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
        const rows = await page.getByTestId("equipment-registry-table").locator("tbody > tr").count();
        expect(rows).toBeLessThanOrEqual(80);
      }
    });

    await test.step("keep viewer read-only across all Equipment asset categories", async () => {
      const detailsSearch = page.getByPlaceholder("Код, inventory, business key, модель або серійний номер");

      await detailsSearch.fill("MET-SENSOR-EXP");
      await page.getByRole("button", { name: "Переглянути паспорт MET-SENSOR-EXP" }).click();
      const sensorDialog = page.getByRole("dialog", { name: "Паспорт MET-SENSOR-EXP" });
      await expect(sensorDialog).toBeVisible();
      await expect(sensorDialog.getByText("MET-SN-EXP", { exact: true })).toBeVisible();
      await expect(sensorDialog.getByText("Межа metrology contract", { exact: true })).toBeVisible();
      await expect(sensorDialog.getByRole("button", { name: "Редагувати метадані" })).toHaveCount(0);
      await expect(sensorDialog.getByText("Доступ лише для перегляду.", { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Закрити паспорт обладнання" }).click();

      await detailsSearch.fill("reg-le01mp:12");
      await page.getByRole("button", { name: "Переглянути паспорт reg-le01mp:12" }).click();
      const meterDialog = page.getByRole("dialog", { name: "Паспорт reg-le01mp:12" });
      await expect(meterDialog).toBeVisible();
      await expect(meterDialog.getByText("Modbus unit id", { exact: true })).toBeVisible();
      await expect(meterDialog.getByRole("button", { name: "Редагувати метадані" })).toHaveCount(0);
      await expect(meterDialog.getByText("Доступ лише для перегляду.", { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Закрити паспорт обладнання" }).click();

      await detailsSearch.fill("REG-REF-ACTIVE");
      await page.getByRole("button", { name: "Переглянути паспорт REG-REF-ACTIVE" }).click();
      const refrigerationDialog = page.getByRole("dialog", { name: "Паспорт REG-REF-ACTIVE" });
      await expect(refrigerationDialog).toBeVisible();
      await expect(refrigerationDialog.getByRole("button", { name: "Редагувати метадані" })).toHaveCount(0);
      await expect(refrigerationDialog.getByRole("link", { name: "Канонічна картка" })).toHaveAttribute(
        "href",
        `/refrigeration/${activeEquipmentId}`,
      );
      await page.getByRole("button", { name: "Закрити паспорт обладнання" }).click();
      await detailsSearch.fill("");
    });

    await test.step("navigate to the canonical refrigeration mutation workflow", async () => {
      await page
        .getByPlaceholder("Код, inventory, business key, модель або серійний номер")
        .fill("REG-REF-ACTIVE");
      const link = page.getByRole("link", { name: "Відкрити канонічну картку REG-REF-ACTIVE" });
      await expect(link).toHaveAttribute("href", `/refrigeration/${activeEquipmentId}`);
      await link.click();
      await expect(page).toHaveURL(new RegExp(`/refrigeration/${activeEquipmentId}$`));
    });

    await test.step("allow engineer safe metadata edits without acquisition mutation", async () => {
      const engineerContext = await authenticatedContext(browser, engineerToken);
      try {
        const engineerPage = await engineerContext.newPage();
        const engineerRequests = observeRegistryRequests(engineerPage);
        const engineerAcquisitionMutations: string[] = [];
        engineerPage.on("request", (request) => {
          const pathname = new URL(request.url()).pathname;
          if (request.method() !== "GET" && pathname.includes("acquisition-registry")) {
            engineerAcquisitionMutations.push(`${request.method()} ${pathname}`);
          }
        });

        await engineerPage.goto("/equipment", { waitUntil: "domcontentloaded" });
        await expect(engineerPage.getByText(/Каталоги \d+\/\d+/, { exact: true })).toHaveCount(0);
        const search = engineerPage.getByPlaceholder(
          "Код, inventory, business key, модель або серійний номер",
        );

        await search.fill("MET-SENSOR-EDIT");
        await engineerPage.getByRole("button", { name: "Переглянути паспорт MET-SENSOR-EDIT" }).click();
        const sensorDialog = engineerPage.getByRole("dialog", { name: "Паспорт MET-SENSOR-EDIT" });
        await sensorDialog.getByRole("button", { name: "Редагувати метадані" }).click();
        await expect(sensorDialog.getByText(/channel mapping залишаються read-only/)).toBeVisible();
        await expect(sensorDialog.getByLabel("Позиція сенсора", { exact: true })).toHaveCount(0);
        await sensorDialog.getByLabel("Серійний номер").fill("MET-SN-EDITED");
        await sensorDialog.getByLabel("Статус калібрування").selectOption("current");
        await sensorDialog.getByRole("button", { name: "Зберегти" }).click();
        await expect(sensorDialog.getByText("MET-SN-EDITED", { exact: true })).toBeVisible();
        await expect(sensorDialog.getByText("Актуальне", { exact: true })).toBeVisible();
        await engineerPage.getByRole("button", { name: "Закрити паспорт обладнання" }).click();

        await search.fill("met-edit-device:18");
        await engineerPage.getByRole("button", { name: "Переглянути паспорт met-edit-device:18" }).click();
        const meterDialog = engineerPage.getByRole("dialog", { name: "Паспорт met-edit-device:18" });
        await meterDialog.getByRole("button", { name: "Редагувати метадані" }).click();
        await expect(
          meterDialog.getByText(/Modbus Unit ID 18 і transport identity залишаються read-only/),
        ).toBeVisible();
        await expect(meterDialog.getByLabel(/Modbus Unit ID/i)).toHaveCount(0);
        await meterDialog.getByLabel("Назва").fill("Metadata Edit Device Updated");
        await engineerPage.getByRole("button", { name: "Закрити паспорт обладнання" }).click();
        await expect(meterDialog.getByText("Є незбережені зміни", { exact: true })).toBeVisible();
        await meterDialog.getByRole("button", { name: "Продовжити редагування" }).click();
        await expect(meterDialog.getByLabel("Назва")).toHaveValue("Metadata Edit Device Updated");
        await meterDialog.getByRole("button", { name: "Зберегти" }).click();
        await expect(meterDialog.getByText("Metadata Edit Device Updated", { exact: true })).toBeVisible();
        await engineerPage.getByRole("button", { name: "Закрити паспорт обладнання" }).click();

        await search.fill("REG-REF-ACTIVE");
        await engineerPage.getByRole("button", { name: "Переглянути паспорт REG-REF-ACTIVE" }).click();
        const refrigerationDialog = engineerPage.getByRole("dialog", { name: "Паспорт REG-REF-ACTIVE" });
        await expect(refrigerationDialog.getByRole("button", { name: "Редагувати метадані" })).toBeVisible();
        await expect(refrigerationDialog.getByRole("link", { name: "Канонічна картка" })).toHaveAttribute(
          "href",
          `/refrigeration/${activeEquipmentId}`,
        );
        await engineerPage.screenshot({
          path: path.join(evidenceDirectory, "equipment-registry-permissioned-metadata.png"),
          fullPage: true,
        });

        await expect
          .poll(() => engineerRequests.filter((request) => request.method !== "GET").length)
          .toBe(2);
        expect(engineerRequests.every((request) => request.authorization)).toBe(true);
        expect(engineerRequests.every((request) => request.organization === organizationId)).toBe(true);
        expect(
          engineerRequests
            .filter((request) => request.method !== "GET")
            .map((request) => `${request.method} ${request.pathname}`),
        ).toEqual([
          `PATCH /api/v1/climate-chambers/${chamberAId}/physical-sensors/66500000-0000-4000-8000-000000000005`,
          `PATCH /api/v1/climate-chambers/${chamberAId}/measurement-devices/66300000-0000-4000-8000-000000000005`,
        ]);
        expect(engineerAcquisitionMutations).toEqual([]);
      } finally {
        await engineerContext.close();
      }
    });

    await expect.poll(() => requests.length).toBeGreaterThanOrEqual(5);
    expect(requests.every((request) => request.authorization)).toBe(true);
    expect(requests.every((request) => request.organization === organizationId)).toBe(true);
    expect(requests.filter((request) => request.method !== "GET")).toEqual([]);
    expect(acquisitionMutations).toEqual([]);

    expect(
      databaseScalar(
        `SELECT COUNT(*) FROM security_audit_events WHERE organization_id = '${organizationId}' AND actor_subject = 'equipment-engineer-acceptance' AND action IN ('measurement_device.metadata_updated', 'physical_sensor.metadata_updated')`,
      ),
    ).toBe("2");
    expect(
      databaseScalar(
        `SELECT unit_id::text FROM measurement_devices WHERE organization_id = '${organizationId}' AND business_key = 'met-edit-device:18'`,
      ),
    ).toBe("18");
    expect(
      databaseScalar(
        `SELECT sensor_position FROM physical_sensors WHERE organization_id = '${organizationId}' AND inventory_number = 'MET-SENSOR-EDIT'`,
      ),
    ).toBe("B");

    writeDatabaseEvidence();
    writeFileSync(
      path.join(evidenceDirectory, "equipment-registry-summary.json"),
      `${JSON.stringify(
        {
          organizationId,
          expectedAssetCount,
          fixtures: {
            lifecycle: ["active", "maintenance", "retired"],
            connection: ["connected", "disconnected", "unknown"],
            calibration: ["current", "due", "expired", "untracked"],
            failedChamber: chamberBId,
          },
          injectedFailureCount,
          registryRequests: requests,
          canonicalDetailPath: `/refrigeration/${activeEquipmentId}`,
          mutationsObserved: requests.filter((request) => request.method !== "GET").length,
        },
        null,
        2,
      )}\n`,
    );
  } finally {
    releaseChamberA();
    await context.close();
    cleanupEquipmentRegistryScaleFixtures();
  }
});

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for Equipment Registry acceptance`);
  return value;
}
