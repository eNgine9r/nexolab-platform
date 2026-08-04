import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";

const organizationId = requiredEnvironment("NEXOLAB_DASHBOARD_ORGANIZATION_ID");
const viewerToken = requiredEnvironment("NEXOLAB_DASHBOARD_VIEWER_TOKEN");
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

const expectedAssetCount = 10;

type ObservedRegistryRequest = {
  method: string;
  pathname: string;
  authorization: boolean;
  organization: string | null;
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
      "SELECT business_key, device_type, connection_status, climate_chamber_id",
      "FROM measurement_devices",
      `WHERE organization_id = '${organizationId}' AND business_key LIKE 'reg-%'`,
      "ORDER BY business_key;",
      "SELECT inventory_number, calibration_status, status, climate_chamber_id",
      "FROM physical_sensors",
      `WHERE organization_id = '${organizationId}' AND inventory_number LIKE 'MET-SENSOR-%'`,
      "ORDER BY inventory_number;",
    ].join(" "),
  ]);
  writeFileSync(path.join(evidenceDirectory, "equipment-registry-database-state.txt"), output);
}

test("renders and navigates the authenticated Equipment and metrology registry", async ({ browser }) => {
  seedEquipmentRegistryFixtures();
  const context = await authenticatedContext(browser);
  const page = await context.newPage();
  const requests = observeRegistryRequests(page);
  let injectedFailureCount = 0;

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
      await expect(
        page.getByText(`Показано ${expectedAssetCount} із ${expectedAssetCount}`, { exact: true }),
      ).toBeVisible();

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
        await expect(page.getByText(identifier, { exact: true })).toBeVisible();
      }

      await expect(page.getByText("Підключено", { exact: true }).first()).toBeVisible();
      await expect(page.getByText("Відключено", { exact: true }).first()).toBeVisible();
      await expect(page.getByText("Невідомо", { exact: true }).first()).toBeVisible();
      await expect(page.getByText("Актуальне", { exact: true }).first()).toBeVisible();
      await expect(page.getByText("Наближається термін", { exact: true }).first()).toBeVisible();
      await expect(page.getByText("Прострочене", { exact: true }).first()).toBeVisible();
      await expect(page.getByText("Не відстежується", { exact: true }).first()).toBeVisible();
      await expect(page.getByText("Частина chamber catalog недоступна", { exact: true })).toBeVisible();
      await expect(page.getByText("REG-B · Registry Chamber B", { exact: false })).toBeVisible();
      expect(injectedFailureCount).toBeGreaterThan(0);

      await expect.poll(() => requests.length).toBeGreaterThanOrEqual(4);
      expect(requests.every((request) => request.authorization)).toBe(true);
      expect(requests.every((request) => request.organization === organizationId)).toBe(true);
      expect(requests.every((request) => request.method === "GET")).toBe(true);
    });

    await test.step("persist combined physical-sensor filters through the URL and reload", async () => {
      const search = page.getByPlaceholder("Код, inventory, business key, модель або серійний номер");
      await search.fill("MET-SENSOR-EXP");
      await page.getByLabel("Категорія активу").selectOption("physical-sensor");
      await page.getByLabel("Кліматична камера").selectOption(chamberAId);
      await page.getByLabel("Статус").selectOption("connected");
      await page.getByLabel("Статус калібрування").selectOption("expired");

      await expect(page.getByText(`Показано 1 із ${expectedAssetCount}`, { exact: true })).toBeVisible();
      await expect(page.getByText("MET-SENSOR-EXP", { exact: true })).toBeVisible();
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
      await expect(search).toHaveValue("MET-SENSOR-EXP");
      await expect(page.getByLabel("Категорія активу")).toHaveValue("physical-sensor");
      await expect(page.getByLabel("Кліматична камера")).toHaveValue(chamberAId);
      await expect(page.getByLabel("Статус")).toHaveValue("connected");
      await expect(page.getByLabel("Статус калібрування")).toHaveValue("expired");
      await expect(page.getByText(`Показано 1 із ${expectedAssetCount}`, { exact: true })).toBeVisible();

      await page.getByRole("button", { name: "Очистити" }).click();
      await expect(
        page.getByText(`Показано ${expectedAssetCount} із ${expectedAssetCount}`, { exact: true }),
      ).toBeVisible();
    });

    await test.step("combine manufacturer, device class and connection filters", async () => {
      await page.getByLabel("Категорія активу").selectOption("energy-meter");
      await page.getByLabel("Виробник").selectOption("TOMZN");
      await page.getByLabel("Статус").selectOption("disconnected");
      await expect(page.getByText(`Показано 1 із ${expectedAssetCount}`, { exact: true })).toBeVisible();
      await expect(page.getByText("reg-le01mp:12", { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Очистити" }).click();
      await expect(
        page.getByText(`Показано ${expectedAssetCount} із ${expectedAssetCount}`, { exact: true }),
      ).toBeVisible();
    });

    await test.step("show category-specific read-only details without fabricated metrology data", async () => {
      await page.getByRole("button", { name: "Переглянути паспорт MET-SENSOR-EXP" }).click();
      const sensorDialog = page.getByRole("dialog", { name: "Паспорт MET-SENSOR-EXP" });
      await expect(sensorDialog).toBeVisible();
      await expect(sensorDialog.getByText("MET-SN-EXP", { exact: true })).toBeVisible();
      await expect(sensorDialog.getByText("Межа metrology contract", { exact: true })).toBeVisible();
      await expect(sensorDialog.getByText("Дата калібрування", { exact: true })).toHaveCount(0);
      await expect(sensorDialog.getByText("Номер сертифіката", { exact: true })).toHaveCount(0);
      await page.getByRole("button", { name: "Закрити паспорт обладнання" }).click();
      await expect(sensorDialog).toBeHidden();

      await page.getByRole("button", { name: "Переглянути паспорт reg-le01mp:12" }).click();
      const meterDialog = page.getByRole("dialog", { name: "Паспорт reg-le01mp:12" });
      await expect(meterDialog).toBeVisible();
      await expect(meterDialog.getByText("Modbus unit id", { exact: true })).toBeVisible();
      await expect(meterDialog.getByText("Відключено", { exact: true })).toBeVisible();
      await expect(
        meterDialog.getByText("Редагування для цього типу не реалізоване", { exact: true }),
      ).toBeVisible();
      await page.getByRole("button", { name: "Закрити паспорт обладнання" }).click();
      await expect(meterDialog).toBeHidden();

      await page.getByRole("button", { name: "Переглянути паспорт REG-REF-ACTIVE" }).click();
      const refrigerationDialog = page.getByRole("dialog", { name: "Паспорт REG-REF-ACTIVE" });
      await expect(refrigerationDialog).toBeVisible();
      await expect(refrigerationDialog.getByText("Активне", { exact: true })).toBeVisible();
      await expect(
        refrigerationDialog.getByRole("link", { name: "Відкрити канонічну картку" }),
      ).toHaveAttribute("href", `/refrigeration/${activeEquipmentId}`);
      await page.screenshot({
        path: path.join(evidenceDirectory, "equipment-registry-read-only-details.png"),
        fullPage: true,
      });
      await page.getByRole("button", { name: "Закрити паспорт обладнання" }).click();
      await expect(refrigerationDialog).toBeHidden();
    });

    await test.step("navigate to the canonical refrigeration mutation workflow", async () => {
      const link = page.getByRole("link", { name: "Відкрити канонічну картку REG-REF-ACTIVE" });
      await expect(link).toHaveAttribute("href", `/refrigeration/${activeEquipmentId}`);
      await link.click();
      await expect(page).toHaveURL(new RegExp(`/refrigeration/${activeEquipmentId}$`));
    });

    await expect.poll(() => requests.length).toBeGreaterThanOrEqual(5);
    expect(requests.every((request) => request.authorization)).toBe(true);
    expect(requests.every((request) => request.organization === organizationId)).toBe(true);
    expect(requests.filter((request) => request.method !== "GET")).toEqual([]);

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
    await context.close();
  }
});

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for Equipment Registry acceptance`);
  return value;
}
