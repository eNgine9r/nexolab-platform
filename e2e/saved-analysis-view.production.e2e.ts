import { execFileSync } from "node:child_process";
import { createHmac, randomUUID } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Browser, type BrowserContext, type Page, type Request } from "@playwright/test";

// Issue #1688 / #1666: the saved analysis view of a Saved Dashboard, end to end against the real
// telemetry-service and PostgreSQL. An operator saves hidden series, range and chart detail; a reload
// and a fresh browser restore them; a viewer cannot save; an older client that omits `view_settings`
// keeps the stored view, an explicit null clears it, and a corrupted stored value never breaks loading.

const organizationId = requiredEnvironment("NEXOLAB_DASHBOARD_ORGANIZATION_ID");
const evidenceDirectory = process.env.NEXOLAB_DASHBOARD_EVIDENCE_DIR ?? "dashboard-acceptance-evidence";
const composeProject = requiredEnvironment("COMPOSE_PROJECT_NAME");
const baseCompose = requiredEnvironment("NEXOLAB_DASHBOARD_BASE_COMPOSE");
const acceptanceCompose = requiredEnvironment("NEXOLAB_DASHBOARD_ACCEPTANCE_COMPOSE");
const postgresUser = process.env.POSTGRES_USER?.trim() || "nexolab";
const postgresDatabase = process.env.POSTGRES_DB?.trim() || "nexolab";
const apiBaseUrl = requiredEnvironment("NEXT_PUBLIC_NEXOLAB_API_BASE_URL");

const OPERATOR_SUBJECT = "saved-view-operator-1688";
const OPERATOR_IDENTITY_ID = "cccccccc-cccc-cccc-cccc-cccccccc1688";
const OPERATOR_MEMBERSHIP_ID = "dddddddd-dddd-dddd-dddd-dddddddd1688";
const SIX_HOURS_MS = 6 * 60 * 60_000;
const SAVED_DENSITY = 2500;

type DashboardFixture = { dashboardId: string; dashboardName: string; source: string };

type ApiDashboard = {
  id: string;
  name: string;
  description: string | null;
  refresh_seconds: number;
  time_window: string;
  version: number;
  items: Array<{
    channel_id: string;
    metric: string;
    node_id?: string | null;
    equipment_id?: string | null;
    visualization: string;
    color: string | null;
    display_unit: string | null;
  }>;
  view_settings?: Record<string, unknown> | null;
};

function composeExec(args: string[], input?: string): string {
  return execFileSync(
    "docker",
    [
      "compose",
      "--project-name",
      composeProject,
      "--file",
      baseCompose,
      "--file",
      acceptanceCompose,
      ...args,
    ],
    { encoding: "utf8", input, stdio: [input === undefined ? "ignore" : "pipe", "pipe", "pipe"] },
  );
}

function postgres(sql: string): string {
  return composeExec([
    "exec",
    "-T",
    "postgres",
    "psql",
    "-U",
    postgresUser,
    "-d",
    postgresDatabase,
    "-v",
    "ON_ERROR_STOP=1",
    "-tAc",
    sql,
  ]);
}

function sqlString(value: string): string {
  return `'${value.replaceAll("'", "''")}'`;
}

function lastLine(output: string): string {
  return output.trim().split(/\n/).at(-1)?.trim() ?? "";
}

function signToken(subject: string, name: string): string {
  const encode = (value: object) => Buffer.from(JSON.stringify(value)).toString("base64url");
  const now = Math.floor(Date.now() / 1000);
  const header = encode({ alg: "HS256", typ: "JWT" });
  const payload = encode({
    sub: subject,
    email: `${subject}@example.test`,
    name,
    iss: requiredEnvironment("AUTH_JWT_ISSUER"),
    aud: requiredEnvironment("AUTH_JWT_AUDIENCE"),
    iat: now,
    exp: now + 1800,
  });
  const signature = createHmac("sha256", requiredEnvironment("AUTH_JWT_PUBLIC_KEY"))
    .update(`${header}.${payload}`)
    .digest("base64url");
  return `${header}.${payload}.${signature}`;
}

/** A real operator membership with the production permission bundle for Saved Dashboards. */
function seedOperator(): string {
  postgres(`
INSERT INTO security_identities (id, provider, subject, email, display_name, is_active)
VALUES (${sqlString(OPERATOR_IDENTITY_ID)}, 'acceptance-oidc', ${sqlString(OPERATOR_SUBJECT)},
  'saved-view-operator@example.test', 'Saved View Operator', true)
ON CONFLICT (provider, subject) DO UPDATE SET is_active = true;
INSERT INTO security_organization_memberships (id, organization_id, identity_id, is_active)
VALUES (${sqlString(OPERATOR_MEMBERSHIP_ID)}, ${sqlString(organizationId)}, ${sqlString(OPERATOR_IDENTITY_ID)}, true)
ON CONFLICT (organization_id, identity_id) DO UPDATE SET is_active = true;
INSERT INTO security_membership_roles (membership_id, role, assigned_by)
VALUES (${sqlString(OPERATOR_MEMBERSHIP_ID)}, 'operator', 'saved-view-acceptance')
ON CONFLICT (membership_id, role) DO NOTHING;
INSERT INTO security_membership_permissions (membership_id, permission, assigned_by)
VALUES
  (${sqlString(OPERATOR_MEMBERSHIP_ID)}, 'dashboard.read', 'saved-view-acceptance'),
  (${sqlString(OPERATOR_MEMBERSHIP_ID)}, 'live_dashboards.manage', 'saved-view-acceptance'),
  (${sqlString(OPERATOR_MEMBERSHIP_ID)}, 'telemetry.read', 'saved-view-acceptance'),
  (${sqlString(OPERATOR_MEMBERSHIP_ID)}, 'alerts.read', 'saved-view-acceptance')
ON CONFLICT (membership_id, permission) DO NOTHING;
`);
  return signToken(OPERATOR_SUBJECT, "Saved View Operator");
}

/** Three plotted line series of one metric/unit, each with persisted history in the last 20 minutes. */
function seedDashboard(): DashboardFixture {
  const dashboardId = randomUUID();
  const suffix = Date.now().toString();
  const dashboardName = `Saved View ${suffix}`;
  const source = `saved-view-acceptance-${suffix}`;
  const itemIds = [randomUUID(), randomUUID(), randomUUID()];
  const output = postgres(`
INSERT INTO live_dashboards (
  id, organization_id, name, description, owner_subject, refresh_seconds, time_window,
  version, status, created_by, updated_by, created_at, updated_at
)
VALUES (
  ${sqlString(dashboardId)}, ${sqlString(organizationId)}, ${sqlString(dashboardName)},
  'Saved analysis view acceptance', 'acceptance-fixture', 2, '1h', 1, 'active',
  'acceptance-fixture', 'acceptance-fixture', NOW(), NOW()
);

WITH candidates AS (
  SELECT channel.id, channel.channel_id, channel.metric_type, channel.unit
  FROM measurement_channels AS channel
  JOIN measurement_devices AS device
    ON device.organization_id = channel.organization_id
   AND device.id = channel.device_id
  WHERE channel.organization_id = ${sqlString(organizationId)}
    AND channel.status = 'active'
    AND device.device_type IN ('temperature_controller', 'energy_meter')
    AND device.unit_id BETWEEN 1 AND 247
),
group_choice AS (
  SELECT metric_type, unit
  FROM candidates
  GROUP BY metric_type, unit
  HAVING COUNT(*) >= 3
  ORDER BY CASE WHEN metric_type = 'temperature.probe' THEN 0 ELSE 1 END, metric_type, unit
  LIMIT 1
),
ranked AS (
  SELECT
    candidates.id,
    candidates.channel_id,
    candidates.metric_type,
    candidates.unit,
    ROW_NUMBER() OVER (ORDER BY candidates.channel_id, candidates.id) AS position
  FROM candidates
  JOIN group_choice
    ON group_choice.metric_type = candidates.metric_type
   AND group_choice.unit = candidates.unit
)
INSERT INTO live_dashboard_items (
  id, organization_id, dashboard_id, position, channel_ref_id, channel_id, metric,
  native_unit, visualization, color, display_unit
)
SELECT
  CASE ranked.position
    WHEN 1 THEN ${sqlString(itemIds[0])}
    WHEN 2 THEN ${sqlString(itemIds[1])}
    ELSE ${sqlString(itemIds[2])}
  END,
  ${sqlString(organizationId)}, ${sqlString(dashboardId)}, ranked.position, ranked.id,
  ranked.channel_id, ranked.metric_type, ranked.unit, 'line',
  CASE ranked.position WHEN 1 THEN '#00C6E0' WHEN 2 THEN '#7ED321' ELSE '#A855F7' END,
  ranked.unit
FROM ranked
WHERE ranked.position <= 3;

INSERT INTO telemetry_samples (
  event_id, node_id, captured_at, metric, value, unit, quality, source,
  equipment_id, channel_id, alarm, raw_value, raw_status, raw_payload
)
SELECT
  md5(item.id || ':' || sample_index::text),
  bus.node_id,
  NOW() - ((5 - sample_index) * INTERVAL '4 minutes'),
  item.metric,
  (item.position * 10 + sample_index)::double precision,
  item.native_unit,
  'valid',
  ${sqlString(source)},
  CASE device.device_type
    WHEN 'temperature_controller' THEN 'K' || device.unit_id::text
    WHEN 'energy_meter' THEN 'LE01MP-' || device.unit_id::text
  END,
  item.channel_id,
  NULL,
  item.position * 100 + sample_index,
  NULL,
  '{}'::json
FROM live_dashboard_items AS item
JOIN measurement_channels AS channel
  ON channel.organization_id = item.organization_id
 AND channel.id = item.channel_ref_id
JOIN measurement_devices AS device
  ON device.organization_id = channel.organization_id
 AND device.id = channel.device_id
JOIN measurement_buses AS bus
  ON bus.organization_id = channel.organization_id
 AND bus.id = channel.bus_id
CROSS JOIN generate_series(1, 4) AS sample_index
WHERE item.dashboard_id = ${sqlString(dashboardId)};

SELECT
  (SELECT COUNT(*) FROM live_dashboard_items WHERE dashboard_id = ${sqlString(dashboardId)})::text || '|' ||
  (SELECT COUNT(*) FROM telemetry_samples WHERE source = ${sqlString(source)})::text;
`);
  const [items, samples] = lastLine(output).split("|");
  if (items !== "3") throw new Error(`Saved view dashboard seeded ${items || "0"} items instead of 3`);
  if (samples !== "12")
    throw new Error(`Saved view dashboard seeded ${samples || "0"} samples instead of 12`);
  return { dashboardId, dashboardName, source };
}

function removeDashboard(fixture: DashboardFixture): void {
  postgres(`
BEGIN;
DELETE FROM live_dashboard_items WHERE dashboard_id = ${sqlString(fixture.dashboardId)};
DELETE FROM live_dashboards WHERE id = ${sqlString(fixture.dashboardId)};
DELETE FROM telemetry_samples WHERE source = ${sqlString(fixture.source)};
COMMIT;
`);
}

function storedViewSettings(dashboardId: string): unknown {
  const raw = lastLine(
    postgres(
      `SELECT COALESCE(view_settings::text, 'null') FROM live_dashboards WHERE id = ${sqlString(dashboardId)};`,
    ),
  );
  return JSON.parse(raw) as unknown;
}

async function api(
  token: string,
  method: "GET" | "PUT",
  dashboardId: string,
  options: { body?: unknown; ifMatch?: string } = {},
): Promise<{ status: number; etag: string | null; body: unknown }> {
  const response = await fetch(`${apiBaseUrl}/api/v1/live-dashboards/${dashboardId}`, {
    method,
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
      "X-Organization-ID": organizationId,
      ...(options.body === undefined ? {} : { "Content-Type": "application/json" }),
      ...(options.ifMatch ? { "If-Match": options.ifMatch } : {}),
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  const text = await response.text();
  return {
    status: response.status,
    etag: response.headers.get("etag"),
    body: text ? JSON.parse(text) : null,
  };
}

/** The write body exactly as a client released before #1666 would send it: no `view_settings` key. */
function olderClientBody(dashboard: ApiDashboard, description: string): Record<string, unknown> {
  return {
    name: dashboard.name,
    description,
    refresh_seconds: dashboard.refresh_seconds,
    time_window: dashboard.time_window,
    items: dashboard.items.map((item) => ({
      channel_id: item.channel_id,
      metric: item.metric,
      node_id: item.node_id ?? null,
      equipment_id: item.equipment_id ?? null,
      visualization: item.visualization,
      color: item.color,
      display_unit: item.display_unit,
    })),
  };
}

async function tokenContext(browser: Browser, token: string): Promise<BrowserContext> {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
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

function observeHistoryRanges(page: Page): number[] {
  const ranges: number[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    // Raw pages or aggregated history (P0 charts) both carry the requested window.
    if (
      !url.pathname.endsWith("/api/v1/telemetry/history") &&
      !url.pathname.endsWith("/api/v1/telemetry/history/aggregate")
    )
      return;
    const from = Date.parse(url.searchParams.get("from") ?? "");
    const to = Date.parse(url.searchParams.get("to") ?? "");
    if (Number.isFinite(from) && Number.isFinite(to)) ranges.push(to - from);
  });
  return ranges;
}

async function openDashboard(page: Page, fixture: DashboardFixture) {
  await page.goto("/live?workspace=dashboards", { waitUntil: "domcontentloaded" });
  await expect(page.getByText(fixture.dashboardName, { exact: true })).toBeVisible();
  await page
    .locator("article")
    .filter({ hasText: fixture.dashboardName })
    .getByRole("button", { name: "Відкрити" })
    .click();
  await expect(page.getByRole("heading", { name: fixture.dashboardName, exact: true })).toBeVisible();
  const panel = page.getByTestId("saved-dashboard-chart-panel");
  await expect(panel).toHaveCount(1);
  await expect(panel.getByTestId("chart-accessible-summary")).toBeVisible();
  return panel;
}

const densitySelect = (page: Page) => page.getByLabel("Деталізація / точок на лінію");

test("operator saves the analysis view and it is restored from PostgreSQL", async ({ browser }) => {
  test.setTimeout(240_000);
  mkdirSync(evidenceDirectory, { recursive: true });
  const operatorToken = seedOperator();
  const viewerToken = signToken("viewer-acceptance", "Viewer Acceptance");
  const fixture = seedDashboard();
  const evidence: Record<string, unknown> = { dashboardId: fixture.dashboardId };
  const contexts: BrowserContext[] = [];

  try {
    let hiddenSeriesName = "";
    let savedSettings: Record<string, unknown> = {};

    await test.step("operator hides a series, picks 6h and a chart detail, and saves the view", async () => {
      const context = await tokenContext(browser, operatorToken);
      contexts.push(context);
      const page = await context.newPage();
      const ranges = observeHistoryRanges(page);
      const panel = await openDashboard(page, fixture);
      const controls = page.getByTestId("saved-analysis-view-controls");
      await expect(controls).toBeVisible();
      await expect(page.getByTestId("saved-analysis-view-status")).toHaveText("Вигляд ще не збережено.");
      await expect(panel.getByRole("button", { name: /^Приховати / })).toHaveCount(3);

      const rangesBeforeSixHours = ranges.length;
      await page.getByRole("button", { name: "6 годин", exact: true }).click();
      await expect.poll(() => ranges.slice(rangesBeforeSixHours).includes(SIX_HOURS_MS)).toBe(true);
      await expect(page.getByText("Завантаження повної persisted history…")).toHaveCount(0);
      await densitySelect(page).selectOption(String(SAVED_DENSITY));
      await expect(densitySelect(page)).toHaveValue(String(SAVED_DENSITY));
      await expect(page.getByText("Завантаження повної persisted history…")).toHaveCount(0);

      const hide = panel.getByRole("button", { name: /^Приховати / }).first();
      hiddenSeriesName = ((await hide.getAttribute("aria-label")) ?? (await hide.innerText())).replace(
        /^Приховати /,
        "",
      );
      await hide.click();
      await expect(panel.getByRole("button", { name: /^Показати / })).toHaveCount(1);
      await expect(panel.getByRole("button", { name: `Показати ${hiddenSeriesName}` })).toBeVisible();

      const putRequest = page.waitForRequest(
        (request: Request) =>
          request.method() === "PUT" &&
          new URL(request.url()).pathname === `/api/v1/live-dashboards/${fixture.dashboardId}`,
      );
      const putResponse = page.waitForResponse(
        (response) =>
          response.request().method() === "PUT" &&
          new URL(response.url()).pathname === `/api/v1/live-dashboards/${fixture.dashboardId}`,
      );
      await controls.getByRole("button", { name: "Зберегти вигляд аналізу", exact: true }).click();
      const request = await putRequest;
      expect(request.headers()["if-match"]).toBe('W/"live-dashboard-v1"');
      const payload = request.postDataJSON() as { view_settings?: Record<string, unknown> | null };
      expect(payload).toHaveProperty("view_settings");
      const settings = payload.view_settings as Record<string, unknown>;
      expect(settings).toMatchObject({
        schema_version: 1,
        range_kind: "6h",
        range_from: null,
        range_to: null,
        density: SAVED_DENSITY,
      });
      expect(settings.hidden_items).toHaveLength(1);
      expect((await putResponse).status()).toBe(200);
      await expect(page.getByTestId("saved-analysis-view-status")).toContainText("Вигляд збережено");

      const stored = storedViewSettings(fixture.dashboardId) as Record<string, unknown>;
      expect(stored).toMatchObject({
        schema_version: 1,
        range_kind: "6h",
        density: SAVED_DENSITY,
        hidden_items: settings.hidden_items,
      });
      savedSettings = stored;
      evidence.putViewSettings = settings;
      evidence.storedViewSettings = stored;

      await test.step("a page reload restores hidden series, range and chart detail", async () => {
        const rangesBeforeReload = ranges.length;
        await page.reload({ waitUntil: "domcontentloaded" });
        const restored = await openDashboard(page, fixture);
        await expect.poll(() => ranges.slice(rangesBeforeReload).includes(SIX_HOURS_MS)).toBe(true);
        await expect(restored.getByRole("button", { name: `Показати ${hiddenSeriesName}` })).toBeVisible();
        await expect(restored.getByRole("button", { name: /^Показати / })).toHaveCount(1);
        await expect(restored.getByRole("button", { name: /^Приховати / })).toHaveCount(2);
        await expect(densitySelect(page)).toHaveValue(String(SAVED_DENSITY));
        await expect(page.getByTestId("saved-analysis-view-status")).toHaveText(
          "Збережений вигляд застосовується при відкритті.",
        );
      });
      await page.screenshot({ path: path.join(evidenceDirectory, "saved-analysis-view-restored.png") });
    });

    await test.step("a fresh browser without local preferences restores the view from the server", async () => {
      const context = await tokenContext(browser, operatorToken);
      contexts.push(context);
      const page = await context.newPage();
      const ranges = observeHistoryRanges(page);
      const panel = await openDashboard(page, fixture);
      await expect.poll(() => ranges.includes(SIX_HOURS_MS)).toBe(true);
      await expect(panel.getByRole("button", { name: `Показати ${hiddenSeriesName}` })).toBeVisible();
      await expect(panel.getByRole("button", { name: /^Показати / })).toHaveCount(1);
      await expect(densitySelect(page)).toHaveValue(String(SAVED_DENSITY));
    });

    await test.step("a read-only viewer sees the saved view but cannot save it", async () => {
      const context = await tokenContext(browser, viewerToken);
      contexts.push(context);
      const page = await context.newPage();
      const mutations: string[] = [];
      page.on("request", (request) => {
        if (
          !["GET", "HEAD", "OPTIONS"].includes(request.method()) &&
          request.url().includes("/live-dashboards")
        )
          mutations.push(`${request.method()} ${request.url()}`);
      });
      const panel = await openDashboard(page, fixture);
      await expect(page.getByTestId("saved-analysis-view-controls")).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Зберегти вигляд аналізу" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Скинути збережений вигляд" })).toHaveCount(0);
      await expect(panel.getByRole("button", { name: `Показати ${hiddenSeriesName}` })).toBeVisible();
      expect(mutations).toEqual([]);

      const current = await api(viewerToken, "GET", fixture.dashboardId);
      expect(current.status).toBe(200);
      const denied = await api(viewerToken, "PUT", fixture.dashboardId, {
        ifMatch: current.etag ?? undefined,
        body: { ...olderClientBody(current.body as ApiDashboard, "viewer attempt"), view_settings: null },
      });
      expect(denied.status).toBe(403);
      expect(storedViewSettings(fixture.dashboardId)).toEqual(savedSettings);
    });

    await test.step("an older client PUT without view_settings preserves the view; explicit null clears it", async () => {
      const current = await api(operatorToken, "GET", fixture.dashboardId);
      expect(current.status).toBe(200);
      const dashboard = current.body as ApiDashboard;
      expect(dashboard.view_settings).toMatchObject({ range_kind: "6h", density: SAVED_DENSITY });

      const older = await api(operatorToken, "PUT", fixture.dashboardId, {
        ifMatch: current.etag ?? undefined,
        body: olderClientBody(dashboard, "older client update"),
      });
      expect(older.status).toBe(200);
      const afterOlder = older.body as ApiDashboard;
      expect(afterOlder.description).toBe("older client update");
      expect(afterOlder.version).toBe(dashboard.version + 1);
      expect(afterOlder.view_settings).toEqual(dashboard.view_settings);
      expect(storedViewSettings(fixture.dashboardId)).toEqual(savedSettings);

      const cleared = await api(operatorToken, "PUT", fixture.dashboardId, {
        ifMatch: older.etag ?? undefined,
        body: { ...olderClientBody(afterOlder, "older client update"), view_settings: null },
      });
      expect(cleared.status).toBe(200);
      expect((cleared.body as ApiDashboard).view_settings ?? null).toBeNull();
      expect(storedViewSettings(fixture.dashboardId)).toBeNull();
      const reread = await api(operatorToken, "GET", fixture.dashboardId);
      expect((reread.body as ApiDashboard).view_settings ?? null).toBeNull();
      evidence.olderClientPreserved = afterOlder.view_settings;
    });

    await test.step("a corrupted stored view is ignored and the dashboard still loads", async () => {
      const corrupted = [
        { schema_version: 1, hidden_items: "not-a-list", range_kind: "forever", density: 7 },
        { schema_version: 99, hidden_items: [], range_kind: "6h" },
        "not-an-object",
      ];
      for (const value of corrupted) {
        postgres(
          `UPDATE live_dashboards SET view_settings = ${sqlString(JSON.stringify(value))}::json WHERE id = ${sqlString(fixture.dashboardId)};`,
        );
        expect(storedViewSettings(fixture.dashboardId)).toEqual(value);
        const read = await api(operatorToken, "GET", fixture.dashboardId);
        expect(read.status).toBe(200);
        expect((read.body as ApiDashboard).view_settings ?? null).toBeNull();
      }

      const context = await tokenContext(browser, operatorToken);
      contexts.push(context);
      const page = await context.newPage();
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      const panel = await openDashboard(page, fixture);
      await expect(panel.getByRole("button", { name: /^Приховати / })).toHaveCount(3);
      await expect(panel.getByRole("button", { name: /^Показати / })).toHaveCount(0);
      await expect(page.getByTestId("saved-analysis-view-status")).toHaveText("Вигляд ще не збережено.");
      expect(errors).toEqual([]);
      evidence.corruptedValues = corrupted;
    });

    writeFileSync(
      path.join(evidenceDirectory, "saved-analysis-view-summary.json"),
      `${JSON.stringify(evidence, null, 2)}\n`,
    );
  } finally {
    for (const context of contexts) await context.close();
    removeDashboard(fixture);
  }
});

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for saved analysis view acceptance`);
  return value;
}
