import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Browser } from "@playwright/test";

const apiBaseUrl = requiredEnvironment("NEXT_PUBLIC_NEXOLAB_API_BASE_URL");
const organizationId = requiredEnvironment("NEXOLAB_LOCAL_AUTH_ORGANIZATION_ID");
const password = requiredEnvironment("NEXOLAB_LOCAL_AUTH_PASSWORD");
const administrator = requiredEnvironment("NEXOLAB_LOCAL_AUTH_ADMIN_USERNAME");
const viewer = requiredEnvironment("NEXOLAB_LOCAL_AUTH_VIEWER_USERNAME");
const evidenceDirectory = process.env.NEXOLAB_LOCAL_AUTH_EVIDENCE_DIR ?? "local-auth-acceptance-evidence";

async function login(browser: Browser, username: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto("/login", { waitUntil: "networkidle" });
  await page.getByLabel("Логін або email").fill(username);
  await page.getByLabel("Пароль").fill(password);
  await page.getByRole("button", { name: "Увійти" }).click();
  await expect(page.getByLabel("Вийти з NEXOLAB")).toBeVisible();
  const accessToken = await page.evaluate(() =>
    window.sessionStorage.getItem("nexolab.local-auth.access-token"),
  );
  expect(accessToken).toBeTruthy();
  return { context, page, accessToken: accessToken as string };
}

function headers(accessToken: string) {
  return {
    Authorization: `Bearer ${accessToken}`,
    "X-Organization-ID": organizationId,
    Accept: "application/json",
  };
}

test("administrator reads the offline version workspace while non-admin is denied", async ({ browser }) => {
  mkdirSync(evidenceDirectory, { recursive: true });
  const admin = await login(browser, administrator);
  const nonAdmin = await login(browser, viewer);
  try {
    await admin.page.goto("/settings", { waitUntil: "networkidle" });
    const versionLink = admin.page.getByRole("link", { name: /Версія NEXOLAB/ });
    await expect(versionLink).toHaveAttribute("href", "/settings/system/version");
    await versionLink.click();
    await expect(admin.page.getByRole("heading", { name: "Системна версія" })).toBeVisible();
    await expect(admin.page.getByText(/Runtime не має canonical packaged version evidence/)).toBeVisible();
    await expect(admin.page.getByText(/Інших validated packages у локальному catalog немає/)).toBeVisible();

    const adminResponse = await admin.page.request.get(`${apiBaseUrl}/api/v1/system/version`, {
      headers: headers(admin.accessToken),
    });
    expect(adminResponse.status()).toBe(200);
    const snapshot = await adminResponse.json();
    expect(snapshot).toMatchObject({ current: null, catalog: [], history: [], offline: true });

    const deniedResponse = await nonAdmin.page.request.get(`${apiBaseUrl}/api/v1/system/version`, {
      headers: headers(nonAdmin.accessToken),
    });
    expect(deniedResponse.status()).toBe(403);
    expect((await deniedResponse.json()).detail.code).toBe("permission_denied");
    await nonAdmin.page.goto("/settings/system/version", { waitUntil: "networkidle" });
    await expect(nonAdmin.page.getByRole("heading", { name: "Доступ заборонено" })).toBeVisible();

    writeFileSync(
      path.join(evidenceDirectory, "settings-version-evidence.json"),
      `${JSON.stringify(
        {
          administrator_status: adminResponse.status(),
          offline: snapshot.offline,
          current: snapshot.current,
          catalog_count: snapshot.catalog.length,
          non_admin_status: deniedResponse.status(),
          mutation_requested: false,
        },
        null,
        2,
      )}\n`,
      { encoding: "utf-8", mode: 0o600 },
    );
  } finally {
    await admin.context.close();
    await nonAdmin.context.close();
  }
});

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}
