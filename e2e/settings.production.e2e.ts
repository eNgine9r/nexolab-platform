import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";

const organizationId = requiredEnvironment("NEXOLAB_DASHBOARD_ORGANIZATION_ID");
const viewerToken = requiredEnvironment("NEXOLAB_DASHBOARD_VIEWER_TOKEN");
const evidenceDirectory = process.env.NEXOLAB_DASHBOARD_EVIDENCE_DIR ?? "dashboard-acceptance-evidence";
const preferenceStorageKey = "nexolab.settings.preferences.v1";

const expectedApi = sanitizePublicUrl(requiredEnvironment("NEXT_PUBLIC_NEXOLAB_API_BASE_URL"));
const expectedWebsocket = sanitizePublicUrl(
  requiredEnvironment("NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL"),
);
const expectedAuthProvider = requiredEnvironment("NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER").toLowerCase();

type ObservedApiRequest = {
  method: string;
  pathname: string;
  authorization: boolean;
  organization: string | null;
};

async function authenticatedContext(browser: Browser): Promise<BrowserContext> {
  const context = await browser.newContext();
  await context.addInitScript(
    ({ accessToken, organization, storageKey }) => {
      if (window.location.protocol === "about:") return;
      window.sessionStorage.setItem("nexolab.acceptance.access-token", accessToken);
      window.sessionStorage.setItem("nexolab.acceptance.organization-id", organization);
      window.localStorage.setItem(storageKey, "{malformed-settings-json");
    },
    { accessToken: viewerToken, organization: organizationId, storageKey: preferenceStorageKey },
  );
  return context;
}

function observeApiRequests(page: Page): ObservedApiRequest[] {
  const requests: ObservedApiRequest[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/v1/")) return;
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

test("renders operator-safe Settings without backend mutations or secret exposure", async ({
  browser,
}) => {
  mkdirSync(evidenceDirectory, { recursive: true });
  const context = await authenticatedContext(browser);
  const page = await context.newPage();
  const requests = observeApiRequests(page);

  try {
    await test.step("render verified organization context and sanitized runtime diagnostics", async () => {
      await page.goto("/settings", { waitUntil: "domcontentloaded" });
      await expect(page.getByText("Viewer Acceptance", { exact: true }).first()).toBeVisible();
      await expect(page.getByRole("heading", { name: "Налаштування", exact: true })).toBeVisible();
      await expect(page.getByText("NEXOLAB Dashboard Acceptance", { exact: true })).toBeVisible();
      await expect(page.getByText("Спостерігач", { exact: true })).toBeVisible();
      await expect(page.getByText("LOCAL_LAN", { exact: true })).toBeVisible();
      await expect(page.getByText("Live mode", { exact: true })).toBeVisible();
      await expect(page.getByText(expectedAuthProvider, { exact: true })).toBeVisible();
      await expect(page.getByText(expectedApi, { exact: true })).toBeVisible();
      await expect(page.getByText(expectedWebsocket, { exact: true })).toBeVisible();
      await expect(page.getByText("Конфігурація готова", { exact: true })).toBeVisible();

      const bodyText = await page.locator("body").innerText();
      expect(bodyText).not.toContain(viewerToken);
      expect(bodyText).not.toContain("access_token");
      expect(bodyText).not.toContain("password=");
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

      await page.getByRole("button", { name: "Скинути локальні налаштування" }).click();
      await expect(page.getByLabel("Часові позначки")).toHaveValue("local");
      await expect(page.getByLabel("Щільність таблиць")).toHaveValue("comfortable");
      await expect(page.getByLabel("Анімація")).toHaveValue("system");
      await expect(page.getByLabel("Стандартне вікно телеметрії")).toHaveValue("6h");
    });

    await test.step("expose only canonical navigation instead of duplicate administration", async () => {
      await expect(page.getByRole("link", { name: /Вузли/ })).toHaveAttribute("href", "/nodes");
      await expect(page.getByRole("link", { name: /^Обладнання/ })).toHaveAttribute(
        "href",
        "/equipment",
      );
      await expect(page.getByRole("link", { name: /Холодильне обладнання/ })).toHaveAttribute(
        "href",
        "/refrigeration",
      );
      await expect(page.getByRole("link", { name: /Тривоги/ })).toHaveAttribute("href", "/alerts");
      await expect(page.getByRole("link", { name: /Звіти/ })).toHaveAttribute("href", "/reports");

      await page.getByRole("link", { name: /^Обладнання/ }).click();
      await expect(page).toHaveURL(/\/equipment$/);
      await expect(page.getByRole("heading", { name: "Обладнання та метрологія" })).toBeVisible();
      await page.goBack({ waitUntil: "domcontentloaded" });
      await expect(page).toHaveURL(/\/settings$/);
      await expect(page.getByRole("heading", { name: "Налаштування", exact: true })).toBeVisible();
    });

    await expect.poll(() => requests.length).toBeGreaterThan(0);
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
