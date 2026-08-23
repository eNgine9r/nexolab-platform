import { createHmac } from "node:crypto";
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";

const organizationId = requiredEnvironment("NEXOLAB_DASHBOARD_ORGANIZATION_ID");
const viewerToken = requiredEnvironment("NEXOLAB_DASHBOARD_VIEWER_TOKEN");
const evidenceDirectory = process.env.NEXOLAB_DASHBOARD_EVIDENCE_DIR ?? "dashboard-acceptance-evidence";
const preferenceStorageKey = "nexolab.settings.preferences.v1";
const webUrl = requiredEnvironment("NEXOLAB_DASHBOARD_WEB_URL");

const expectedApi = sanitizePublicUrl(requiredEnvironment("NEXT_PUBLIC_NEXOLAB_API_BASE_URL"));
const expectedWebsocket = sanitizePublicUrl(requiredEnvironment("NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL"));
const expectedAuthProvider = requiredEnvironment("NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER").toLowerCase();

type ObservedApiRequest = {
  method: string;
  pathname: string;
  authorization: boolean;
  organization: string | null;
};

async function authenticatedContext(
  browser: Browser,
  accessToken = viewerToken,
  { corruptPreferences = true }: { corruptPreferences?: boolean } = {},
): Promise<BrowserContext> {
  const context = await browser.newContext();
  await context.addInitScript(
    ({ token, organization, storageKey, shouldCorruptPreferences }) => {
      if (window.location.protocol === "about:") return;
      window.sessionStorage.setItem("nexolab.acceptance.access-token", token);
      window.sessionStorage.setItem("nexolab.acceptance.organization-id", organization);
      if (shouldCorruptPreferences && window.localStorage.getItem(storageKey) === null) {
        window.localStorage.setItem(storageKey, "{malformed-settings-json");
      }
    },
    {
      token: accessToken,
      organization: organizationId,
      storageKey: preferenceStorageKey,
      shouldCorruptPreferences: corruptPreferences,
    },
  );
  return context;
}

function observeApiRequests(page: Page): ObservedApiRequest[] {
  const requests: ObservedApiRequest[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/v1/") && url.pathname !== "/api/device-agent/acquisition-cadence") {
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

function seedCadenceEngineer(): void {
  const project = requiredEnvironment("COMPOSE_PROJECT_NAME");
  const baseCompose = requiredEnvironment("NEXOLAB_DASHBOARD_BASE_COMPOSE");
  const acceptanceCompose = requiredEnvironment("NEXOLAB_DASHBOARD_ACCEPTANCE_COMPOSE");
  const postgresUser = requiredEnvironment("POSTGRES_USER");
  const postgresDatabase = requiredEnvironment("POSTGRES_DB");
  const sql = String.raw`
INSERT INTO security_identities (id, provider, subject, email, display_name, is_active)
VALUES (
  'cccccccc-cccc-cccc-cccc-ccccccccccc2',
  'acceptance-oidc',
  'engineer-acceptance',
  'engineer@example.test',
  'Cadence Engineer',
  true
)
ON CONFLICT (provider, subject) DO UPDATE
SET email = EXCLUDED.email, display_name = EXCLUDED.display_name, is_active = true;

INSERT INTO security_organization_memberships (id, organization_id, identity_id, is_active)
VALUES (
  'dddddddd-dddd-dddd-dddd-ddddddddddd2',
  :'organization_id',
  'cccccccc-cccc-cccc-cccc-ccccccccccc2',
  true
)
ON CONFLICT (organization_id, identity_id) DO UPDATE SET is_active = true;

INSERT INTO security_membership_roles (membership_id, role, assigned_by)
VALUES ('dddddddd-dddd-dddd-dddd-ddddddddddd2', 'engineer', 'settings-cadence-acceptance')
ON CONFLICT (membership_id, role) DO NOTHING;

INSERT INTO security_membership_permissions (membership_id, permission, assigned_by)
VALUES
  ('dddddddd-dddd-dddd-dddd-ddddddddddd2', 'dashboard.read', 'settings-cadence-acceptance'),
  ('dddddddd-dddd-dddd-dddd-ddddddddddd2', 'equipment.manage', 'settings-cadence-acceptance')
ON CONFLICT (membership_id, permission) DO NOTHING;
`;
  execFileSync(
    "docker",
    [
      "compose",
      "--project-name",
      project,
      "--file",
      baseCompose,
      "--file",
      acceptanceCompose,
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
      "-v",
      `organization_id=${organizationId}`,
    ],
    { input: sql, stdio: ["pipe", "pipe", "pipe"] },
  );
}

function issueAcceptanceToken(subject: string, email: string, name: string): string {
  const secret = requiredEnvironment("AUTH_JWT_PUBLIC_KEY");
  const issuer = requiredEnvironment("AUTH_JWT_ISSUER");
  const audience = requiredEnvironment("AUTH_JWT_AUDIENCE");
  const now = Math.floor(Date.now() / 1000);
  const encode = (value: object) => Buffer.from(JSON.stringify(value)).toString("base64url");
  const header = encode({ alg: "HS256", typ: "JWT" });
  const payload = encode({
    sub: subject,
    email,
    name,
    iss: issuer,
    aud: audience,
    iat: now,
    exp: now + 1800,
  });
  const signature = createHmac("sha256", secret).update(`${header}.${payload}`).digest("base64url");
  return `${header}.${payload}.${signature}`;
}

test("renders operator-safe Settings without backend mutations or secret exposure", async ({ browser }) => {
  mkdirSync(evidenceDirectory, { recursive: true });
  const context = await authenticatedContext(browser);
  const page = await context.newPage();
  const requests = observeApiRequests(page);

  try {
    await test.step("render verified organization context, persisted cadence and sanitized runtime diagnostics", async () => {
      await page.goto("/settings", { waitUntil: "domcontentloaded" });
      await expect(page.getByText("Viewer Acceptance", { exact: true }).first()).toBeVisible();
      await expect(page.getByRole("heading", { name: "Налаштування", exact: true })).toBeVisible();
      const operatorContext = page.getByRole("region", { name: "Організація та оператор" });
      await expect(operatorContext.getByText("NEXOLAB Dashboard Acceptance", { exact: true })).toBeVisible();
      await expect(operatorContext.getByText("Спостерігач", { exact: true })).toBeVisible();
      const runtimeSummary = page.getByRole("region", { name: "Підсумок runtime configuration" });
      await expect(runtimeSummary.getByText("LOCAL_LAN", { exact: true })).toBeVisible();
      await expect(page.getByText("Live mode", { exact: true })).toBeVisible();
      await expect(page.getByText(expectedAuthProvider, { exact: true })).toBeVisible();
      await expect(page.getByText(expectedApi, { exact: true })).toBeVisible();
      await expect(page.getByText(expectedWebsocket, { exact: true })).toBeVisible();
      const readyStatus = page.getByText("Конфігурація готова", { exact: true });
      await expect(readyStatus).toHaveCount(2);
      await expect(readyStatus.first()).toBeVisible();

      const cadence = page.getByRole("region", { name: "Фізичний інтервал опитування" });
      await expect(cadence).toBeVisible();
      await expect(cadence.getByText("Registry revision: 7", { exact: true })).toBeVisible();
      await expect(cadence.getByText(/Доступ лише для перегляду/)).toBeVisible();
      await expect(cadence.getByText("Dixell XJP60D", { exact: true }).first()).toBeVisible();
      await expect(cadence.getByText("LE-01MP / енергомоніторинг", { exact: true }).first()).toBeVisible();
      await expect(cadence.getByText(/Refresh графіків.*не змінюють фізичне/)).toBeVisible();

      const bodyText = await page.locator("body").innerText();
      expect(bodyText).not.toContain(viewerToken);
      expect(bodyText).not.toContain("access_token");
      expect(bodyText).not.toContain("password=");
      expect(bodyText).not.toContain("127.0.0.1:18081");
    });

    await test.step("recover malformed local preferences, persist approved values and reset", async () => {
      await expect(
        page.getByText("Пошкоджені локальні налаштування відновлено", { exact: true }),
      ).toBeVisible();

      await page.getByLabel("Часові позначки").selectOption("utc");
      await page.getByLabel("Щільність таблиць").selectOption("compact");
      await page.getByLabel("Анімація").selectOption("reduced");
      await page.getByLabel("Стандартне вікно телеметрії").selectOption("24h");

      await expect
        .poll(async () => {
          return page.evaluate((storageKey) => window.localStorage.getItem(storageKey), preferenceStorageKey);
        })
        .toContain('"telemetryWindow":"24h"');

      await page.reload({ waitUntil: "domcontentloaded" });
      await expect(page.getByLabel("Часові позначки")).toHaveValue("utc");
      await expect(page.getByLabel("Щільність таблиць")).toHaveValue("compact");
      await expect(page.getByLabel("Анімація")).toHaveValue("reduced");
      await expect(page.getByLabel("Стандартне вікно телеметрії")).toHaveValue("24h");
      await expect(page.getByText("Registry revision: 7", { exact: true })).toBeVisible();

      await page.getByRole("button", { name: "Скинути локальні налаштування" }).click();
      await expect(page.getByLabel("Часові позначки")).toHaveValue("local");
      await expect(page.getByLabel("Щільність таблиць")).toHaveValue("comfortable");
      await expect(page.getByLabel("Анімація")).toHaveValue("system");
      await expect(page.getByLabel("Стандартне вікно телеметрії")).toHaveValue("6h");
    });

    await test.step("expose only canonical navigation instead of duplicate administration", async () => {
      const nodesLink = page.getByRole("link", {
        name: "Вузли Інвентар, стан і канонічні node workflows.",
        exact: true,
      });
      const equipmentLink = page.getByRole("link", {
        name: "Обладнання Read-only asset та metrology registry.",
        exact: true,
      });
      const refrigerationLink = page.getByRole("link", {
        name: "Холодильне обладнання Підтримувані passport і layout mutations.",
        exact: true,
      });
      const alertsLink = page.getByRole("link", {
        name: "Тривоги Перегляд і дозволені alarm operations.",
        exact: true,
      });
      const reportsLink = page.getByRole("link", {
        name: "Звіти Формування, погодження та експорт доказів.",
        exact: true,
      });

      await expect(nodesLink).toHaveAttribute("href", "/nodes");
      await expect(equipmentLink).toHaveAttribute("href", "/equipment");
      await expect(refrigerationLink).toHaveAttribute("href", "/refrigeration");
      await expect(alertsLink).toHaveAttribute("href", "/alerts");
      await expect(reportsLink).toHaveAttribute("href", "/reports");

      await equipmentLink.click();
      await expect(page).toHaveURL(/\/equipment$/);
      await expect(page.getByRole("heading", { name: "Обладнання та метрологія" })).toBeVisible();
      await page.goBack({ waitUntil: "domcontentloaded" });
      await expect(page).toHaveURL(/\/settings$/);
      await expect(page.getByRole("heading", { name: "Налаштування", exact: true })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Фізичний інтервал опитування" })).toBeVisible();
    });

    await expect.poll(() => requests.length).toBeGreaterThan(0);
    expect(requests.some((request) => request.pathname === "/api/device-agent/acquisition-cadence")).toBe(
      true,
    );
    expect(requests.filter((request) => request.method !== "GET")).toEqual([]);
    expect(requests.every((request) => request.authorization)).toBe(true);
    expect(requests.every((request) => request.organization === organizationId)).toBe(true);

    await page.screenshot({
      path: path.join(evidenceDirectory, "settings-operator-safe-workspace.png"),
      fullPage: true,
    });
    writeFileSync(
      path.join(evidenceDirectory, "settings-summary.json"),
      `${JSON.stringify(
        {
          organizationId,
          runtime: {
            api: expectedApi,
            websocket: expectedWebsocket,
            authProvider: expectedAuthProvider,
          },
          preferences: {
            malformedRecoveryVerified: true,
            persistenceVerified: true,
            resetVerified: true,
          },
          acquisitionCadence: {
            readThroughAuthenticatedLoopbackProxy: true,
            registryRevision: 7,
            viewerMutationControlsDisabled: true,
            physicalPollingSeparatedFromPresentation: true,
          },
          canonicalNavigation: "/equipment",
          apiRequests: requests,
          mutationsObserved: requests.filter((request) => request.method !== "GET").length,
          secretExposureObserved: false,
        },
        null,
        2,
      )}\n`,
    );
  } finally {
    await context.close();
  }
});

test("persists safe cadence and fails closed on capacity and stale revision", async ({ browser }) => {
  seedCadenceEngineer();
  const engineerToken = issueAcceptanceToken(
    "engineer-acceptance",
    "engineer@example.test",
    "Cadence Engineer",
  );
  const context = await authenticatedContext(browser, engineerToken, { corruptPreferences: false });
  const page = await context.newPage();
  const requests = observeApiRequests(page);

  try {
    await page.goto("/settings", { waitUntil: "domcontentloaded" });
    await expect(page.getByText("Cadence Engineer", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Інженер", { exact: true })).toBeVisible();

    const cadence = page.getByRole("region", { name: "Фізичний інтервал опитування" });
    await expect(cadence.getByText("Registry revision: 7", { exact: true })).toBeVisible();
    await expect(cadence.getByText(/Доступ лише для перегляду/)).toHaveCount(0);

    const xjpFamilyCard = cadence.locator("article").filter({ hasText: "Dixell XJP60D" }).first();
    await expect(xjpFamilyCard).toBeVisible();

    await test.step("apply safe family preset and re-read canonical revision", async () => {
      await xjpFamilyCard.getByRole("button", { name: "30 с" }).click();
      await xjpFamilyCard.getByRole("button", { name: "Застосувати" }).click();
      await expect(cadence.getByText("Registry revision: 8", { exact: true })).toBeVisible();
      await expect(xjpFamilyCard.getByText("Family default · 30 с", { exact: true })).toBeVisible();

      await page.reload({ waitUntil: "domcontentloaded" });
      const reloadedCadence = page.getByRole("region", { name: "Фізичний інтервал опитування" });
      await expect(reloadedCadence.getByText("Registry revision: 8", { exact: true })).toBeVisible();
      await expect(xjpFamilyCard.getByText("Family default · 30 с", { exact: true })).toBeVisible();
    });

    await test.step("reject unsafe 10-second preset without changing persisted revision", async () => {
      const currentCadence = page.getByRole("region", { name: "Фізичний інтервал опитування" });
      const currentXjpFamilyCard = currentCadence
        .locator("article")
        .filter({ hasText: "Dixell XJP60D" })
        .filter({ hasText: "Family default · 30 с" })
        .first();
      await currentXjpFamilyCard.getByRole("button", { name: "10 с" }).click();
      await currentXjpFamilyCard.getByRole("button", { name: "Застосувати" }).click();

      const alert = currentCadence.getByRole("alert");
      await expect(alert).toContainText("Запитаний інтервал небезпечний для активної RS-485 шини");
      await expect(alert).toContainText("рекомендовано не швидше 30 с");
      await expect(currentCadence.getByText("Registry revision: 8", { exact: true })).toBeVisible();
      await expect(currentXjpFamilyCard.getByText("Family default · 30 с", { exact: true })).toBeVisible();
      await expect(currentCadence.getByRole("button", { name: /force|примус/i })).toHaveCount(0);
    });

    await test.step("reject stale revision and refresh canonical state", async () => {
      const externalMutation = await context.request.put(
        new URL("/api/device-agent/acquisition-cadence", webUrl).toString(),
        {
          headers: {
            Authorization: `Bearer ${engineerToken}`,
            "X-Organization-Id": organizationId,
            Accept: "application/json",
          },
          data: {
            expected_revision: 8,
            reason: "Acceptance fixture concurrent LE cadence update",
            family_defaults: [{ bus_id: "rs485-main", device_family: "le01mp", interval_seconds: 60 }],
          },
        },
      );
      expect(externalMutation.status()).toBe(200);

      const currentCadence = page.getByRole("region", { name: "Фізичний інтервал опитування" });
      const currentXjpFamilyCard = currentCadence
        .locator("article")
        .filter({ hasText: "Dixell XJP60D" })
        .filter({ hasText: "Family default · 30 с" })
        .first();
      await currentXjpFamilyCard.getByRole("button", { name: "60 с" }).click();
      await currentXjpFamilyCard.getByRole("button", { name: "Застосувати" }).click();

      await expect(currentCadence.getByRole("alert")).toContainText("Конфлікт версії cadence policy");
      await expect(currentCadence.getByText("Registry revision: 9", { exact: true })).toBeVisible();
      await expect(currentXjpFamilyCard.getByText("Family default · 30 с", { exact: true })).toBeVisible();
    });

    const browserCadenceMutations = requests.filter(
      (request) => request.pathname === "/api/device-agent/acquisition-cadence" && request.method === "PUT",
    );
    expect(browserCadenceMutations).toHaveLength(3);
    expect(requests.every((request) => request.authorization)).toBe(true);
    expect(requests.every((request) => request.organization === organizationId)).toBe(true);

    await page.screenshot({
      path: path.join(evidenceDirectory, "settings-acquisition-cadence-control.png"),
      fullPage: true,
    });
    writeFileSync(
      path.join(evidenceDirectory, "settings-acquisition-cadence-summary.json"),
      `${JSON.stringify(
        {
          safePresetPersistedAfterReload: true,
          unsafeCapacityRejectedWithoutRevisionChange: true,
          staleRevisionRejectedAndCanonicalStateReloaded: true,
          finalRegistryRevision: 9,
          directBrowserDeviceAgentAccess: false,
          forceBypassAvailable: false,
          browserCadenceMutations: browserCadenceMutations.length,
        },
        null,
        2,
      )}\n`,
    );
  } finally {
    await context.close();
  }
});

function sanitizePublicUrl(value: string): string {
  const parsed = new URL(value);
  parsed.username = "";
  parsed.password = "";
  parsed.search = "";
  parsed.hash = "";
  const pathname = parsed.pathname === "/" ? "" : parsed.pathname.replace(/\/+$/, "");
  return `${parsed.origin}${pathname}`;
}

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for Settings acceptance`);
  return value;
}
