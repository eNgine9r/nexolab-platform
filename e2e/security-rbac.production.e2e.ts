import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";

const organizationId =
  process.env.NEXOLAB_SECURITY_ORGANIZATION_ID ?? "11111111-1111-1111-1111-111111111111";
const otherOrganizationId =
  process.env.NEXOLAB_SECURITY_OTHER_ORGANIZATION_ID ?? "22222222-2222-2222-2222-222222222222";
const apiBaseUrl =
  process.env.NEXT_PUBLIC_NEXOLAB_API_BASE_URL ?? "http://127.0.0.1:18092";
const evidenceDirectory =
  process.env.NEXOLAB_SECURITY_EVIDENCE_DIR ?? "security-acceptance-evidence";
const equipmentId = "showcase-106-01";
const equipmentRoute = `/refrigeration/${equipmentId}`;
const equipmentPhoto = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAABAAAAAKCAIAAAAy3EnLAAAAF0lEQVR4nGPkUbJgIAUwkaR6VMOg0QAA11IAejJlKAQAAAAASUVORK5CYII=",
  "base64",
);

const tokens = {
  viewer: requiredEnvironment("NEXOLAB_VIEWER_TOKEN"),
  operator: requiredEnvironment("NEXOLAB_OPERATOR_TOKEN"),
  engineer: requiredEnvironment("NEXOLAB_ENGINEER_TOKEN"),
  administrator: requiredEnvironment("NEXOLAB_ADMIN_TOKEN"),
};

function apiHeaders(token: string, selectedOrganizationId = organizationId) {
  return {
    Authorization: `Bearer ${token}`,
    "X-Organization-ID": selectedOrganizationId,
    "Content-Type": "application/json",
  };
}

async function authenticatedContext(
  browser: Browser,
  token: string,
  selectedOrganizationId = organizationId,
): Promise<BrowserContext> {
  const context = await browser.newContext();
  await context.addInitScript(
    ({ accessToken, organization }) => {
      window.sessionStorage.setItem("nexolab.acceptance.access-token", accessToken);
      window.sessionStorage.setItem("nexolab.acceptance.organization-id", organization);
    },
    { accessToken: token, organization: selectedOrganizationId },
  );
  return context;
}

async function openEquipment(page: Page) {
  await page.goto(equipmentRoute, { waitUntil: "networkidle" });
  await expect(page.getByText(/Чернетка v\d+ · PostgreSQL/)).toBeVisible();
}

function editor(page: Page) {
  return page.locator("#layout-editor");
}

test("enforces authenticated organization roles and immutable audit attribution", async ({
  browser,
}) => {
  mkdirSync(evidenceDirectory, { recursive: true });

  await test.step("reject an unauthenticated browser before loading protected layout data", async () => {
    const context = await browser.newContext();
    const page = await context.newPage();
    try {
      await page.goto(equipmentRoute, { waitUntil: "networkidle" });
      await expect(page.getByRole("alert")).toContainText(
        "Authorization bearer token is required",
      );
      await expect(page.getByRole("button", { name: "Редагувати схему" })).toHaveCount(0);
    } finally {
      await context.close();
    }
  });

  await test.step("keep viewer read-only in both UI and API", async () => {
    const context = await authenticatedContext(browser, tokens.viewer);
    const page = await context.newPage();
    try {
      await openEquipment(page);
      await expect(page.getByText("viewer", { exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Редагувати схему" })).toHaveCount(0);

      const draftResponse = await context.request.get(
        `${apiBaseUrl}/api/v1/equipment/${equipmentId}/layout/draft`,
        { headers: apiHeaders(tokens.viewer) },
      );
      expect(draftResponse.status()).toBe(200);
      const denied = await context.request.put(
        `${apiBaseUrl}/api/v1/equipment/${equipmentId}/layout/draft`,
        {
          headers: {
            ...apiHeaders(tokens.viewer),
            "If-Match": draftResponse.headers().etag,
          },
          data: { image_id: null, placements: [] },
        },
      );
      expect(denied.status()).toBe(403);
      expect((await denied.json()).detail.code).toBe("permission_denied");
    } finally {
      await context.close();
    }
  });

  await test.step("allow operator draft work but deny publication", async () => {
    const context = await authenticatedContext(browser, tokens.operator);
    const page = await context.newPage();
    try {
      await openEquipment(page);
      await expect(page.getByText("operator", { exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Редагувати схему" }).first()).toBeVisible();
      await expect(
        page.getByRole("button", { name: "Опублікувати поточну чернетку" }),
      ).toHaveCount(0);

      const draftResponse = await context.request.get(
        `${apiBaseUrl}/api/v1/equipment/${equipmentId}/layout/draft`,
        { headers: apiHeaders(tokens.operator) },
      );
      const denied = await context.request.post(
        `${apiBaseUrl}/api/v1/equipment/${equipmentId}/layout/publish`,
        {
          headers: {
            ...apiHeaders(tokens.operator),
            "If-Match": draftResponse.headers().etag,
          },
          data: { actor_id: "spoofed-browser-actor" },
        },
      );
      expect(denied.status()).toBe(403);
    } finally {
      await context.close();
    }
  });

  await test.step("publish as engineer and persist verified actor audit", async () => {
    const context = await authenticatedContext(browser, tokens.engineer);
    const page = await context.newPage();
    try {
      await openEquipment(page);
      await expect(page.getByText("engineer", { exact: true })).toBeVisible();

      await page.getByLabel("Вибрати production-фото обладнання").setInputFiles({
        name: "security-acceptance.png",
        mimeType: "image/png",
        buffer: equipmentPhoto,
      });
      await expect(page.getByText(/завантажено та прив’язано до чернетки v2/)).toBeVisible();

      await editor(page).getByRole("button", { name: "Редагувати схему" }).click();
      await editor(page).getByRole("button", { name: "Скинути позиції" }).click();
      await editor(page).getByRole("button", { name: "Зберегти чернетку" }).click();
      await expect(page.getByText("Чернетку схеми збережено · версія 3")).toBeVisible();

      await page.getByRole("button", { name: "Опублікувати поточну чернетку" }).click();
      await expect(page.getByText("Опубліковано ревізію r1.")).toBeVisible();

      const historyResponse = await context.request.get(
        `${apiBaseUrl}/api/v1/equipment/${equipmentId}/layout/history`,
        { headers: apiHeaders(tokens.engineer) },
      );
      expect(historyResponse.status()).toBe(200);
      const history = await historyResponse.json();
      expect(history.items[0].published_by).toBe("engineer-acceptance");

      const auditResponse = await context.request.get(
        `${apiBaseUrl}/api/v1/audit/events?entity_type=equipment_layout&entity_id=${equipmentId}`,
        { headers: apiHeaders(tokens.engineer) },
      );
      expect(auditResponse.status()).toBe(200);
      const audit = await auditResponse.json();
      expect(audit.items.map((item: { action: string }) => item.action)).toEqual([
        "layout.published",
        "layout.draft.updated",
      ]);
      expect(
        audit.items.every(
          (item: { actor_subject: string }) => item.actor_subject === "engineer-acceptance",
        ),
      ).toBe(true);

      await page.screenshot({
        path: path.join(evidenceDirectory, "engineer-published-layout.png"),
        fullPage: true,
      });
    } finally {
      await context.close();
    }
  });

  await test.step("allow administrator membership management and reject cross-organization access", async () => {
    const context = await authenticatedContext(browser, tokens.administrator);
    try {
      const membershipResponse = await context.request.put(
        `${apiBaseUrl}/api/v1/organizations/${organizationId}/memberships`,
        {
          headers: apiHeaders(tokens.administrator),
          data: {
            provider: "acceptance-oidc",
            subject: "new-viewer-acceptance",
            email: "new-viewer@example.test",
            display_name: "New Viewer",
            roles: ["viewer"],
            reason: "Controlled browser acceptance",
          },
        },
      );
      expect(membershipResponse.status()).toBe(200);
      expect((await membershipResponse.json()).membership.roles).toEqual(["viewer"]);

      const membershipAudit = await context.request.get(
        `${apiBaseUrl}/api/v1/audit/events?entity_type=organization_membership`,
        { headers: apiHeaders(tokens.administrator) },
      );
      expect(membershipAudit.status()).toBe(200);
      expect((await membershipAudit.json()).items[0]).toMatchObject({
        actor_subject: "administrator-acceptance",
        action: "security.membership.upserted",
        reason: "Controlled browser acceptance",
      });

      const crossOrganization = await context.request.get(
        `${apiBaseUrl}/api/v1/equipment/${equipmentId}/layout/draft`,
        { headers: apiHeaders(tokens.administrator, otherOrganizationId) },
      );
      expect(crossOrganization.status()).toBe(403);
      expect((await crossOrganization.json()).detail.code).toBe(
        "organization_membership_not_found",
      );

      writeFileSync(
        path.join(evidenceDirectory, "security-acceptance-summary.json"),
        `${JSON.stringify(
          {
            organizationId,
            unauthenticatedStatus: 401,
            viewerMutationStatus: 403,
            operatorPublishStatus: 403,
            engineerPublishedBy: "engineer-acceptance",
            administratorMembershipManaged: true,
            crossOrganizationStatus: 403,
          },
          null,
          2,
        )}\n`,
      );
    } finally {
      await context.close();
    }
  });
});

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for security acceptance`);
  return value;
}
