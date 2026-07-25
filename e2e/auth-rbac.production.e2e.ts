import { createHmac } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type BrowserContext, type Page } from "@playwright/test";

const equipmentId = "showcase-106-01";
const equipmentRoute = `/refrigeration/${equipmentId}`;
const storageKey = "nexolab.access_token";
const apiBaseUrl = process.env.NEXT_PUBLIC_NEXOLAB_API_BASE_URL ?? "http://127.0.0.1:28082";
const issuer = process.env.AUTH_JWT_ISSUER ?? "https://auth.nexolab.acceptance";
const audience = process.env.AUTH_JWT_AUDIENCE ?? "nexolab-api";
const secret = process.env.AUTH_JWT_SECRET ?? "";
const evidenceDirectory = process.env.NEXOLAB_RBAC_EVIDENCE_DIR ?? "rbac-acceptance-evidence";

type Role = "admin" | "operator" | "viewer";

function encode(value: object): string {
  return Buffer.from(JSON.stringify(value)).toString("base64url");
}

function accessToken(subject: string, organizationId: string, role: Role): string {
  if (secret.length < 32) throw new Error("AUTH_JWT_SECRET must be available to the RBAC test");
  const now = Math.floor(Date.now() / 1000);
  const header = encode({ alg: "HS256", typ: "JWT" });
  const payload = encode({
    iss: issuer,
    aud: audience,
    sub: subject,
    org_id: organizationId,
    role,
    iat: now,
    exp: now + 900,
    jti: `${subject}-${now}`,
    email: `${subject}@example.test`,
    name: subject.replaceAll("-", " "),
  });
  const signature = createHmac("sha256", secret)
    .update(`${header}.${payload}`)
    .digest("base64url");
  return `${header}.${payload}.${signature}`;
}

function authorization(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

async function authenticatedContext(
  browserContextFactory: () => Promise<BrowserContext>,
  token: string,
): Promise<BrowserContext> {
  const context = await browserContextFactory();
  await context.addInitScript(
    ({ key, value }) => window.sessionStorage.setItem(key, value),
    { key: storageKey, value: token },
  );
  return context;
}

async function openEquipment(page: Page, role: Role, organizationId = "laboratory-a") {
  await page.goto(equipmentRoute, { waitUntil: "networkidle" });
  await expect(page.getByText(new RegExp(`${role} · ${organizationId}`))).toBeVisible();
  await expect(page.getByText(/Чернетка v1 · PostgreSQL/)).toBeVisible();
}

test("enforces browser roles, organization isolation and immutable audit visibility", async ({
  browser,
  request,
}) => {
  mkdirSync(evidenceDirectory, { recursive: true });

  const adminToken = accessToken("admin-a", "laboratory-a", "admin");
  const operatorToken = accessToken("operator-a", "laboratory-a", "operator");
  const viewerToken = accessToken("viewer-a", "laboratory-a", "viewer");
  const foreignAdminToken = accessToken("admin-b", "laboratory-b", "admin");

  const contexts: BrowserContext[] = [];
  try {
    await test.step("reject an unauthenticated live browser", async () => {
      const context = await browser.newContext();
      contexts.push(context);
      const page = await context.newPage();
      await page.goto(equipmentRoute, { waitUntil: "networkidle" });

      await expect(page.getByText(/потрібна авторизована операторська сесія/i).first()).toBeVisible();
      await expect(page.getByRole("button", { name: "Редагування заборонено" })).toBeDisabled();
    });

    await test.step("admin binds the equipment and receives full permissions", async () => {
      const context = await authenticatedContext(() => browser.newContext(), adminToken);
      contexts.push(context);
      const page = await context.newPage();
      await openEquipment(page, "admin");

      await expect(page.getByRole("button", { name: "Редагувати схему" })).toBeEnabled();
      await expect(page.getByRole("button", { name: /Завантажити фото|Замінити фото/ })).toBeEnabled();

      const session = await request.get(`${apiBaseUrl}/api/v1/auth/session`, {
        headers: authorization(adminToken),
      });
      expect(session.status()).toBe(200);
      expect((await session.json()).permissions).toContain("audit.read");
    });

    await test.step("viewer remains read-only in UI and receives typed 403", async () => {
      const context = await authenticatedContext(() => browser.newContext(), viewerToken);
      contexts.push(context);
      const page = await context.newPage();
      await openEquipment(page, "viewer");

      await expect(page.getByRole("button", { name: "Редагування заборонено" })).toBeDisabled();
      await expect(page.getByRole("button", { name: /Завантажити фото|Замінити фото/ })).toBeDisabled();
      await expect(page.getByRole("button", { name: "Опублікувати поточну чернетку" })).toBeDisabled();

      const denied = await request.post(`${apiBaseUrl}/api/v1/equipment/${equipmentId}/images`, {
        headers: authorization(viewerToken),
      });
      expect(denied.status()).toBe(403);
      const payload = await denied.json();
      expect(payload.detail.code).toBe("permission_denied");
      expect(payload.detail.permission).toBe("layouts.write");
    });

    await test.step("operator may edit and upload but cannot publish or restore", async () => {
      const context = await authenticatedContext(() => browser.newContext(), operatorToken);
      contexts.push(context);
      const page = await context.newPage();
      await openEquipment(page, "operator");

      await expect(page.getByRole("button", { name: "Редагувати схему" })).toBeEnabled();
      await expect(page.getByRole("button", { name: /Завантажити фото|Замінити фото/ })).toBeEnabled();
      await expect(page.getByRole("button", { name: "Опублікувати поточну чернетку" })).toBeDisabled();

      const denied = await request.post(
        `${apiBaseUrl}/api/v1/equipment/${equipmentId}/layout/publish`,
        {
          headers: {
            ...authorization(operatorToken),
            "If-Match": 'W/"layout-draft-v1"',
          },
          data: { actor_id: "spoofed-browser-actor" },
        },
      );
      expect(denied.status()).toBe(403);
      const payload = await denied.json();
      expect(payload.detail.permission).toBe("layouts.publish");
    });

    await test.step("foreign organization cannot enumerate bound equipment", async () => {
      const response = await request.get(
        `${apiBaseUrl}/api/v1/equipment/${equipmentId}/layout/draft`,
        { headers: authorization(foreignAdminToken) },
      );
      expect(response.status()).toBe(404);
      const payload = await response.json();
      expect(payload.detail.code).toBe("resource_not_found");
      expect(payload.detail.organization_scoped).toBe(true);
    });

    await test.step("admin reads organization-scoped audit without bearer material", async () => {
      const response = await request.get(`${apiBaseUrl}/api/v1/audit/events?limit=100`, {
        headers: authorization(adminToken),
      });
      expect(response.status()).toBe(200);
      const body = await response.text();
      const payload = JSON.parse(body) as {
        items: Array<{ outcome: string; resource_id: string; metadata_payload: unknown }>;
      };
      expect(payload.items.some((item) => item.outcome === "denied")).toBe(true);
      expect(body).not.toContain("Bearer ");
      expect(body).not.toContain(secret);

      writeFileSync(
        path.join(evidenceDirectory, "auth-rbac-summary.json"),
        `${JSON.stringify(
          {
            equipmentId,
            roles: ["viewer", "operator", "admin"],
            organizationIsolation: true,
            deniedAuditPresent: true,
            tokenMaterialPersisted: false,
          },
          null,
          2,
        )}\n`,
      );
    });
  } finally {
    await Promise.all(contexts.map((context) => context.close()));
  }
});
