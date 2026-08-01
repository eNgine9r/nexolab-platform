import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Browser, type Page } from "@playwright/test";

const apiBaseUrl = requiredEnvironment("NEXT_PUBLIC_NEXOLAB_API_BASE_URL");
const organizationId = requiredEnvironment("NEXOLAB_LOCAL_AUTH_ORGANIZATION_ID");
const password = requiredEnvironment("NEXOLAB_LOCAL_AUTH_PASSWORD");
const evidenceDirectory =
  process.env.NEXOLAB_LOCAL_AUTH_EVIDENCE_DIR ?? "local-auth-acceptance-evidence";

const accounts = {
  viewer: requiredEnvironment("NEXOLAB_LOCAL_AUTH_VIEWER_USERNAME"),
  operator: requiredEnvironment("NEXOLAB_LOCAL_AUTH_OPERATOR_USERNAME"),
  administrator: requiredEnvironment("NEXOLAB_LOCAL_AUTH_ADMIN_USERNAME"),
};

type RoleName = keyof typeof accounts;

type BrowserLogin = {
  page: Page;
  accessToken: string;
};

function apiHeaders(accessToken: string): Record<string, string> {
  return {
    Authorization: `Bearer ${accessToken}`,
    "X-Organization-ID": organizationId,
    Accept: "application/json",
  };
}

async function loginThroughBrowser(
  browser: Browser,
  role: RoleName,
): Promise<BrowserLogin> {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto("/login", { waitUntil: "networkidle" });
  await page.getByLabel("Логін або email").fill(accounts[role]);
  await page.getByLabel("Пароль").fill(password);
  await page.getByRole("button", { name: "Увійти" }).click();
  await expect(page).not.toHaveURL(/\/login(?:\?|$)/);
  await expect(page.getByLabel("Вийти з NEXOLAB")).toBeVisible();

  const storage = await page.evaluate(() => ({
    accessToken: window.sessionStorage.getItem("nexolab.local-auth.access-token"),
    refreshPresent: Boolean(
      window.sessionStorage.getItem("nexolab.local-auth.refresh-token"),
    ),
    localTokenKeys: Object.keys(window.localStorage).filter((key) =>
      key.startsWith("nexolab.local-auth."),
    ),
  }));
  expect(storage.accessToken).toBeTruthy();
  expect(storage.refreshPresent).toBe(true);
  expect(storage.localTokenKeys).toEqual([]);
  return { page, accessToken: storage.accessToken as string };
}

test("authenticates local viewer, operator and administrator without an external identity service", async ({
  browser,
}) => {
  mkdirSync(evidenceDirectory, { recursive: true });
  const roleEvidence: Record<string, unknown> = {};

  for (const role of ["viewer", "operator", "administrator"] as const) {
    await test.step(`verify ${role} browser login and server session`, async () => {
      const { page, accessToken } = await loginThroughBrowser(browser, role);
      try {
        const sessionResponse = await page.request.get(
          `${apiBaseUrl}/api/v1/auth/session`,
          { headers: apiHeaders(accessToken) },
        );
        expect(sessionResponse.status()).toBe(200);
        const session = (await sessionResponse.json()) as {
          identity: { provider: string; subject: string };
          memberships: Array<{
            organization_id: string;
            roles: string[];
            permissions: string[];
          }>;
        };
        expect(session.identity.provider).toBe("nexolab-local");
        expect(session.memberships).toHaveLength(1);
        expect(session.memberships[0]?.organization_id).toBe(organizationId);
        expect(session.memberships[0]?.roles).toContain(role);

        const auditResponse = await page.request.get(
          `${apiBaseUrl}/api/v1/audit/events`,
          { headers: apiHeaders(accessToken) },
        );
        if (role === "administrator") {
          expect(auditResponse.status()).toBe(200);
          expect(session.memberships[0]?.permissions).toContain("audit.read");
        } else {
          expect(auditResponse.status()).toBe(403);
          expect(session.memberships[0]?.permissions).not.toContain("audit.read");
        }
        if (role === "operator") {
          expect(session.memberships[0]?.permissions).toContain("layout.draft.edit");
        }
        if (role === "viewer") {
          expect(session.memberships[0]?.permissions).not.toContain("layout.draft.edit");
        }

        roleEvidence[role] = {
          provider: session.identity.provider,
          subject: session.identity.subject,
          roles: session.memberships[0]?.roles,
          audit_status: auditResponse.status(),
        };
      } finally {
        await page.context().close();
      }
    });
  }

  writeFileSync(
    path.join(evidenceDirectory, "browser-role-evidence.json"),
    `${JSON.stringify(roleEvidence, null, 2)}\n`,
    { encoding: "utf-8", mode: 0o600 },
  );
});

test("rotates refresh tokens and rejects the previous access token after browser logout", async ({
  browser,
}) => {
  const { page, accessToken } = await loginThroughBrowser(browser, "administrator");
  try {
    const refreshBefore = await page.evaluate(() =>
      window.sessionStorage.getItem("nexolab.local-auth.refresh-token"),
    );
    expect(refreshBefore).toBeTruthy();

    await page.evaluate(() => {
      window.sessionStorage.setItem("nexolab.local-auth.access-expires-at", "1");
    });
    await page.reload({ waitUntil: "networkidle" });
    await expect(page.getByLabel("Вийти з NEXOLAB")).toBeVisible();

    const refreshAfter = await page.evaluate(() =>
      window.sessionStorage.getItem("nexolab.local-auth.refresh-token"),
    );
    expect(refreshAfter).toBeTruthy();
    expect(refreshAfter).not.toBe(refreshBefore);

    const currentAccessToken = await page.evaluate(() =>
      window.sessionStorage.getItem("nexolab.local-auth.access-token"),
    );
    expect(currentAccessToken).toBeTruthy();
    const activeResponse = await page.request.get(
      `${apiBaseUrl}/api/v1/auth/session`,
      { headers: apiHeaders(currentAccessToken as string) },
    );
    expect(activeResponse.status()).toBe(200);

    await page.getByLabel("Вийти з NEXOLAB").click();
    await expect
      .poll(async () =>
        await page.evaluate(() => ({
          access: window.sessionStorage.getItem("nexolab.local-auth.access-token"),
          refresh: window.sessionStorage.getItem("nexolab.local-auth.refresh-token"),
        })),
      )
      .toEqual({ access: null, refresh: null });

    const revokedCurrentResponse = await page.request.get(
      `${apiBaseUrl}/api/v1/auth/session`,
      { headers: apiHeaders(currentAccessToken as string) },
    );
    expect(revokedCurrentResponse.status()).toBe(401);
    expect((await revokedCurrentResponse.json()).detail.code).toBe(
      "local_session_invalid",
    );

    const preRefreshResponse = await page.request.get(
      `${apiBaseUrl}/api/v1/auth/session`,
      { headers: apiHeaders(accessToken) },
    );
    expect(preRefreshResponse.status()).toBe(401);
  } finally {
    await page.context().close();
  }
});

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}
