import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Browser, type Page } from "@playwright/test";

const apiBaseUrl = requiredEnvironment("NEXT_PUBLIC_NEXOLAB_API_BASE_URL");
const organizationId = requiredEnvironment("NEXOLAB_LOCAL_AUTH_ORGANIZATION_ID");
const password = requiredEnvironment("NEXOLAB_LOCAL_AUTH_PASSWORD");
const evidenceDirectory = process.env.NEXOLAB_LOCAL_AUTH_EVIDENCE_DIR ?? "local-auth-acceptance-evidence";

const accounts = {
  viewer: requiredEnvironment("NEXOLAB_LOCAL_AUTH_VIEWER_USERNAME"),
  operator: requiredEnvironment("NEXOLAB_LOCAL_AUTH_OPERATOR_USERNAME"),
  administrator: requiredEnvironment("NEXOLAB_LOCAL_AUTH_ADMIN_USERNAME"),
};

type RoleName = keyof typeof accounts;

type BrowserLogin = {
  page: Page;
  accessToken: string;
  refreshToken: string;
};

function apiHeaders(accessToken: string): Record<string, string> {
  return {
    Authorization: `Bearer ${accessToken}`,
    "X-Organization-ID": organizationId,
    Accept: "application/json",
  };
}

async function loginWithCredentials(
  browser: Browser,
  username: string,
  accountPassword: string,
): Promise<BrowserLogin> {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto("/login", { waitUntil: "networkidle" });
  await page.getByLabel("Логін або email").fill(username);
  await page.getByLabel("Пароль").fill(accountPassword);
  await page.getByRole("button", { name: "Увійти" }).click();
  await expect(page).not.toHaveURL(/\/login(?:\?|$)/);
  await expect(page.getByLabel("Вийти з NEXOLAB")).toBeVisible();

  const storage = await page.evaluate(() => ({
    accessToken: window.sessionStorage.getItem("nexolab.local-auth.access-token"),
    refreshToken: window.sessionStorage.getItem("nexolab.local-auth.refresh-token"),
    localTokenKeys: Object.keys(window.localStorage).filter((key) => key.startsWith("nexolab.local-auth.")),
  }));
  expect(storage.accessToken).toBeTruthy();
  expect(storage.refreshToken).toBeTruthy();
  expect(storage.localTokenKeys).toEqual([]);
  return {
    page,
    accessToken: storage.accessToken as string,
    refreshToken: storage.refreshToken as string,
  };
}

async function loginThroughBrowser(browser: Browser, role: RoleName): Promise<BrowserLogin> {
  return loginWithCredentials(browser, accounts[role], password);
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
        const sessionResponse = await page.request.get(`${apiBaseUrl}/api/v1/auth/session`, {
          headers: apiHeaders(accessToken),
        });
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

        const auditResponse = await page.request.get(`${apiBaseUrl}/api/v1/audit/events`, {
          headers: apiHeaders(accessToken),
        });
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

test("administrator provisions every product role with bounded server-side access", async ({ browser }) => {
  mkdirSync(evidenceDirectory, { recursive: true });
  const username = "issue385.engineer";
  const { page: adminPage, accessToken: adminToken } = await loginThroughBrowser(browser, "administrator");
  try {
    await adminPage.goto("/settings/users", { waitUntil: "networkidle" });
    await expect(adminPage.getByRole("heading", { name: "Користувачі та права" })).toBeVisible();
    const adminSession = await adminPage.request.get(`${apiBaseUrl}/api/v1/auth/session`, {
      headers: apiHeaders(adminToken),
    });
    expect(adminSession.status()).toBe(200);
    const adminPermissions = (await adminSession.json()).memberships[0]?.permissions as string[];
    expect(adminPermissions).toContain("memberships.manage");
    expect(adminPermissions).toContain("project_versions.manage");
    await adminPage.getByRole("button", { name: "Новий користувач" }).click();

    const createPanel = adminPage
      .getByRole("heading", { name: "Створити локального користувача" })
      .locator("..");
    await createPanel.getByLabel("Логін").fill(username);
    await createPanel.getByLabel("Ім’я").fill("Issue 385 Engineer");
    await createPanel.getByLabel("Початковий пароль").fill(password);
    await createPanel.getByRole("combobox", { name: "Роль", exact: true }).selectOption("engineer");
    await createPanel.getByRole("checkbox", { name: /Огляд/ }).check();
    await createPanel.getByRole("checkbox", { name: /Перегляд телеметрії/ }).check();
    await createPanel.getByRole("button", { name: "Створити" }).click();

    await expect(adminPage.getByText(`Користувача ${username} створено.`)).toBeVisible();
    await expect(adminPage.getByRole("heading", { name: "Issue 385 Engineer", exact: true })).toBeVisible();

    for (const fixture of [
      {
        username: "issue385.manager",
        role: "laboratory_manager",
        permissions: ["dashboard.read", "reports.read"],
      },
      {
        username: "issue385.technician",
        role: "laboratory_technician",
        permissions: ["telemetry.read"],
      },
    ]) {
      const created = await adminPage.request.post(`${apiBaseUrl}/api/v1/admin/users`, {
        headers: apiHeaders(adminToken),
        data: {
          username: fixture.username,
          password,
          display_name: `Issue 385 ${fixture.role}`,
          role: fixture.role,
          permissions: fixture.permissions,
          reason: "deterministic local-auth production acceptance",
        },
      });
      expect(created.status()).toBe(201);
      const payload = await created.json();
      expect(payload.role).toBe(fixture.role);
      expect(payload.effective_permissions).toEqual(fixture.permissions);
      expect(JSON.stringify(payload)).not.toContain(password);
    }
  } finally {
    await adminPage.context().close();
  }

  for (const fixture of [
    {
      username: "issue385.manager",
      role: "laboratory_manager",
      permissions: ["dashboard.read", "reports.read"],
    },
    {
      username: "issue385.technician",
      role: "laboratory_technician",
      permissions: ["telemetry.read"],
    },
  ]) {
    const { page, accessToken } = await loginWithCredentials(browser, fixture.username, password);
    try {
      const session = await page.request.get(`${apiBaseUrl}/api/v1/auth/session`, {
        headers: apiHeaders(accessToken),
      });
      expect(session.status()).toBe(200);
      expect((await session.json()).memberships[0]).toMatchObject({
        roles: [fixture.role],
        permissions: fixture.permissions,
      });
      const denied = await page.request.get(`${apiBaseUrl}/api/v1/admin/users`, {
        headers: apiHeaders(accessToken),
      });
      expect(denied.status()).toBe(403);
    } finally {
      await page.context().close();
    }
  }

  const { page: engineerPage, accessToken } = await loginWithCredentials(browser, username, password);
  try {
    const sessionResponse = await engineerPage.request.get(`${apiBaseUrl}/api/v1/auth/session`, {
      headers: apiHeaders(accessToken),
    });
    expect(sessionResponse.status()).toBe(200);
    const session = (await sessionResponse.json()) as {
      memberships: Array<{ roles: string[]; permissions: string[] }>;
    };
    expect(session.memberships[0]?.roles).toEqual(["engineer"]);
    expect(session.memberships[0]?.permissions).toEqual(["dashboard.read", "telemetry.read"]);

    const adminApiResponse = await engineerPage.request.get(`${apiBaseUrl}/api/v1/admin/users`, {
      headers: apiHeaders(accessToken),
    });
    expect(adminApiResponse.status()).toBe(403);

    await engineerPage.goto("/settings/users", { waitUntil: "networkidle" });
    await expect(engineerPage.getByRole("heading", { name: "Доступ заборонено" })).toBeVisible();
  } finally {
    await engineerPage.context().close();
  }

  writeFileSync(
    path.join(evidenceDirectory, "user-admin-evidence.json"),
    `${JSON.stringify(
      {
        username,
        role: "engineer",
        permissions: ["dashboard.read", "telemetry.read"],
        non_admin_admin_api_status: 403,
      },
      null,
      2,
    )}\n`,
    { encoding: "utf-8", mode: 0o600 },
  );
});

test("revokes sessions across access and account lifecycle changes", async ({ browser }) => {
  test.setTimeout(300_000);
  mkdirSync(evidenceDirectory, { recursive: true });
  const replacementPassword = `Reset-${password}`;
  const { page: adminPage, accessToken: adminToken } = await loginThroughBrowser(browser, "administrator");
  const lifecycleEvidence: Record<string, unknown> = {};

  try {
    const usersResponse = await adminPage.request.get(`${apiBaseUrl}/api/v1/admin/users`, {
      headers: apiHeaders(adminToken),
    });
    expect(usersResponse.status()).toBe(200);
    const users = (await usersResponse.json()) as {
      items: Array<{ id: string; username: string; role: string; is_active: boolean }>;
    };
    const engineer = users.items.find((item) => item.username === "issue385.engineer");
    const administrator = users.items.find((item) => item.username === accounts.administrator);
    expect(engineer).toBeTruthy();
    expect(administrator).toBeTruthy();

    let engineerLogin = await loginWithCredentials(browser, "issue385.engineer", password);
    const permissionsChanged = await adminPage.request.put(
      `${apiBaseUrl}/api/v1/admin/users/${engineer?.id}/permissions`,
      {
        headers: apiHeaders(adminToken),
        data: {
          permissions: ["dashboard.read", "nodes.read"],
          reason: "local production acceptance permission change",
        },
      },
    );
    expect(permissionsChanged.status()).toBe(200);
    expect((await permissionsChanged.json()).effective_permissions).toEqual(["dashboard.read", "nodes.read"]);
    expect(
      (
        await engineerLogin.page.request.get(`${apiBaseUrl}/api/v1/auth/session`, {
          headers: apiHeaders(engineerLogin.accessToken),
        })
      ).status(),
    ).toBe(401);
    expect(
      (
        await engineerLogin.page.request.post(`${apiBaseUrl}/api/v1/auth/local/refresh`, {
          data: { refresh_token: engineerLogin.refreshToken },
        })
      ).status(),
    ).toBe(401);
    await engineerLogin.page.context().close();

    engineerLogin = await loginWithCredentials(browser, "issue385.engineer", password);
    const updatedSession = await engineerLogin.page.request.get(`${apiBaseUrl}/api/v1/auth/session`, {
      headers: apiHeaders(engineerLogin.accessToken),
    });
    expect(updatedSession.status()).toBe(200);
    expect((await updatedSession.json()).memberships[0]?.permissions).toEqual([
      "dashboard.read",
      "nodes.read",
    ]);

    const roleChanged = await adminPage.request.patch(`${apiBaseUrl}/api/v1/admin/users/${engineer?.id}`, {
      headers: apiHeaders(adminToken),
      data: {
        role: "laboratory_technician",
        reason: "local production acceptance role change",
      },
    });
    expect(roleChanged.status()).toBe(200);
    expect((await roleChanged.json()).role).toBe("laboratory_technician");
    expect(
      (
        await engineerLogin.page.request.get(`${apiBaseUrl}/api/v1/auth/session`, {
          headers: apiHeaders(engineerLogin.accessToken),
        })
      ).status(),
    ).toBe(401);
    await engineerLogin.page.context().close();

    engineerLogin = await loginWithCredentials(browser, "issue385.engineer", password);
    const deactivated = await adminPage.request.patch(`${apiBaseUrl}/api/v1/admin/users/${engineer?.id}`, {
      headers: apiHeaders(adminToken),
      data: { is_active: false, reason: "local production acceptance deactivation" },
    });
    expect(deactivated.status()).toBe(200);
    expect((await deactivated.json()).is_active).toBe(false);
    expect(
      (
        await engineerLogin.page.request.get(`${apiBaseUrl}/api/v1/auth/session`, {
          headers: apiHeaders(engineerLogin.accessToken),
        })
      ).status(),
    ).toBe(401);
    expect(
      (
        await engineerLogin.page.request.post(`${apiBaseUrl}/api/v1/auth/local/refresh`, {
          data: { refresh_token: engineerLogin.refreshToken },
        })
      ).status(),
    ).toBe(401);
    await engineerLogin.page.context().close();
    const inactiveLogin = await adminPage.request.post(`${apiBaseUrl}/api/v1/auth/local/login`, {
      data: { username: "issue385.engineer", password },
    });
    expect([401, 403]).toContain(inactiveLogin.status());

    const reactivated = await adminPage.request.patch(`${apiBaseUrl}/api/v1/admin/users/${engineer?.id}`, {
      headers: apiHeaders(adminToken),
      data: { is_active: true, reason: "local production acceptance reactivation" },
    });
    expect(reactivated.status()).toBe(200);
    expect((await reactivated.json()).is_active).toBe(true);
    engineerLogin = await loginWithCredentials(browser, "issue385.engineer", password);

    const passwordReset = await adminPage.request.post(
      `${apiBaseUrl}/api/v1/admin/users/${engineer?.id}/reset-password`,
      {
        headers: apiHeaders(adminToken),
        data: {
          password: replacementPassword,
          reason: "local production acceptance password reset",
        },
      },
    );
    expect(passwordReset.status()).toBe(204);
    expect(await passwordReset.body()).toHaveLength(0);
    expect(
      (
        await engineerLogin.page.request.get(`${apiBaseUrl}/api/v1/auth/session`, {
          headers: apiHeaders(engineerLogin.accessToken),
        })
      ).status(),
    ).toBe(401);
    await engineerLogin.page.context().close();
    const oldPasswordLogin = await adminPage.request.post(`${apiBaseUrl}/api/v1/auth/local/login`, {
      data: { username: "issue385.engineer", password },
    });
    expect(oldPasswordLogin.status()).toBe(401);
    const replacementLogin = await loginWithCredentials(browser, "issue385.engineer", replacementPassword);
    await replacementLogin.page.context().close();

    for (const data of [
      { is_active: false, reason: "local production acceptance final administrator deactivation" },
      { role: "engineer", reason: "local production acceptance final administrator demotion" },
    ]) {
      const protectedResponse = await adminPage.request.patch(
        `${apiBaseUrl}/api/v1/admin/users/${administrator?.id}`,
        { headers: apiHeaders(adminToken), data },
      );
      expect(protectedResponse.status()).toBe(409);
    }

    const auditResponse = await adminPage.request.get(`${apiBaseUrl}/api/v1/audit/events`, {
      headers: apiHeaders(adminToken),
    });
    expect(auditResponse.status()).toBe(200);
    const auditText = await auditResponse.text();
    expect(auditText).not.toContain(password);
    expect(auditText).not.toContain(replacementPassword);
    expect(auditText).not.toMatch(/scrypt\$|access_token|refresh_token|private_key/i);

    Object.assign(lifecycleEvidence, {
      username: "issue385.engineer",
      permission_change_revoked_access_and_refresh: true,
      effective_permissions_after_relogin: ["dashboard.read", "nodes.read"],
      role_change_revoked_session: true,
      role_after_change: "laboratory_technician",
      deactivation_revoked_session_and_denied_login: true,
      reactivation_restored_login: true,
      password_reset_revoked_session: true,
      old_password_denied: true,
      new_password_accepted: true,
      final_administrator_deactivation_status: 409,
      final_administrator_demotion_status: 409,
      audit_redaction: true,
    });
  } finally {
    await adminPage.context().close();
  }

  writeFileSync(
    path.join(evidenceDirectory, "user-lifecycle-evidence.json"),
    `${JSON.stringify(lifecycleEvidence, null, 2)}\n`,
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
    const activeResponse = await page.request.get(`${apiBaseUrl}/api/v1/auth/session`, {
      headers: apiHeaders(currentAccessToken as string),
    });
    expect(activeResponse.status()).toBe(200);

    await page.getByLabel("Вийти з NEXOLAB").click();
    await expect
      .poll(
        async () =>
          await page.evaluate(() => ({
            access: window.sessionStorage.getItem("nexolab.local-auth.access-token"),
            refresh: window.sessionStorage.getItem("nexolab.local-auth.refresh-token"),
          })),
      )
      .toEqual({ access: null, refresh: null });

    const revokedCurrentResponse = await page.request.get(`${apiBaseUrl}/api/v1/auth/session`, {
      headers: apiHeaders(currentAccessToken as string),
    });
    expect(revokedCurrentResponse.status()).toBe(401);
    expect((await revokedCurrentResponse.json()).detail.code).toBe("local_session_invalid");

    const preRefreshResponse = await page.request.get(`${apiBaseUrl}/api/v1/auth/session`, {
      headers: apiHeaders(accessToken),
    });
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
