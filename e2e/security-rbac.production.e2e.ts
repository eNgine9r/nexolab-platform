import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";

const organizationId = process.env.NEXOLAB_SECURITY_ORGANIZATION_ID ?? "11111111-1111-1111-1111-111111111111";
const otherOrganizationId =
  process.env.NEXOLAB_SECURITY_OTHER_ORGANIZATION_ID ?? "22222222-2222-2222-2222-222222222222";
const apiBaseUrl = process.env.NEXT_PUBLIC_NEXOLAB_API_BASE_URL ?? "http://127.0.0.1:18092";
const evidenceDirectory = process.env.NEXOLAB_SECURITY_EVIDENCE_DIR ?? "security-acceptance-evidence";
const climateChamberId = "security-kk2";
let equipmentId = "";
let equipmentRoute = "";
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
      if (window.location.protocol === "about:") return;
      window.sessionStorage.setItem("nexolab.acceptance.access-token", accessToken);
      window.sessionStorage.setItem("nexolab.acceptance.organization-id", organization);
    },
    { accessToken: token, organization: selectedOrganizationId },
  );
  return context;
}

async function provisionEquipmentPassport(browser: Browser): Promise<void> {
  const context = await authenticatedContext(browser, tokens.administrator);
  try {
    const provisionedNode = await context.request.post(`${apiBaseUrl}/api/v1/nodes`, {
      headers: {
        ...apiHeaders(tokens.administrator),
        "Idempotency-Key": "security-acceptance-climate-chamber-v1",
      },
      data: {
        node_id: climateChamberId,
        display_name: "Кліматична камера Security КК2",
        clock_warning_ms: 30000,
        clock_critical_ms: 120000,
      },
    });
    expect(provisionedNode.status()).toBe(201);
    expect((await provisionedNode.json()).node).toMatchObject({
      node_id: climateChamberId,
      state: "pending",
    });

    const activatedNode = await context.request.post(
      `${apiBaseUrl}/api/v1/nodes/${climateChamberId}/activate`,
      {
        headers: apiHeaders(tokens.administrator),
        data: { reason: "Activate security acceptance climate chamber" },
      },
    );
    expect(activatedNode.status()).toBe(200);
    expect((await activatedNode.json()).state).toBe("active");

    const response = await context.request.post(`${apiBaseUrl}/api/v1/equipment`, {
      headers: {
        ...apiHeaders(tokens.administrator),
        "X-Audit-Reason": "Provision security acceptance equipment passport",
      },
      data: {
        code: "SECURITY-CS-106-01",
        name: "Вітрина №106-01",
        location: "Security acceptance · Лабораторія 1 · КК2",
        laboratory: "Security acceptance · Лабораторія 1",
        zone: "КК2",
        node_id: climateChamberId,
        equipment_type: "Холодильна вітрина",
        manufacturer: "ColdStream",
        model: "Premium 1250",
        serial_number: "SECURITY-X-PROD-10601",
        temperature_class: "3M1 (0…+5 °C)",
        lifecycle_status: "active",
        total_sensors: 48,
      },
    });
    expect(response.status()).toBe(201);
    const equipment = (await response.json()) as { id: string; node_id: string };
    expect(equipment.id).toMatch(/^[0-9a-f-]{36}$/);
    expect(equipment.node_id).toBe(climateChamberId);
    equipmentId = equipment.id;
    equipmentRoute = `/refrigeration/${equipmentId}`;

    const draftResponse = await context.request.get(
      `${apiBaseUrl}/api/v1/equipment/${equipmentId}/layout/draft`,
      { headers: apiHeaders(tokens.administrator) },
    );
    expect(draftResponse.status()).toBe(200);
    expect(draftResponse.headers().etag).toBe('W/"layout-draft-v1"');
    expect((await draftResponse.json()).placements).toEqual([]);
  } finally {
    await context.close();
  }
}

async function openEquipment(page: Page) {
  await page.goto(equipmentRoute, { waitUntil: "networkidle" });
  await expect(page.locator("#layout-editor").getByText(/Чернетка v\d+$/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Вітрина №106-01" })).toBeVisible();
}

async function expectAccessRole(page: Page, role: string) {
  const accessDisclosure = page.getByLabel("Інформація про доступ");
  await accessDisclosure.click();
  await expect(page.getByText(role, { exact: true })).toBeVisible();
  await accessDisclosure.click();
}

test("enforces authenticated organization roles and immutable audit attribution", async ({ browser }) => {
  mkdirSync(evidenceDirectory, { recursive: true });
  await provisionEquipmentPassport(browser);

  await test.step("reject an unauthenticated browser before loading protected layout data", async () => {
    const context = await browser.newContext();
    const page = await context.newPage();
    try {
      await page.goto(equipmentRoute, { waitUntil: "networkidle" });
      await expect(page.getByText("Authorization bearer token is required", { exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: /^Редагувати схему(?: та датчики)?$/ })).toHaveCount(0);
    } finally {
      await context.close();
    }
  });

  await test.step("keep viewer read-only in both UI and API", async () => {
    const context = await authenticatedContext(browser, tokens.viewer);
    const page = await context.newPage();
    try {
      await openEquipment(page);
      await expectAccessRole(page, "viewer");
      await expect(page.getByRole("button", { name: /^Редагувати схему(?: та датчики)?$/ })).toBeHidden();

      const draftResponse = await context.request.get(
        `${apiBaseUrl}/api/v1/equipment/${equipmentId}/layout/draft`,
        { headers: apiHeaders(tokens.viewer) },
      );
      expect(draftResponse.status()).toBe(200);
      const denied = await context.request.put(`${apiBaseUrl}/api/v1/equipment/${equipmentId}/layout/draft`, {
        headers: {
          ...apiHeaders(tokens.viewer),
          "If-Match": draftResponse.headers().etag,
        },
        data: { image_id: null, placements: [] },
      });
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
      await expectAccessRole(page, "operator");
      await expect(
        page.getByRole("button", { name: /^Редагувати схему(?: та датчики)?$/ }).first(),
      ).toBeVisible();

      await page.getByRole("button", { name: "Відкрити версії та публікацію схеми" }).click();
      const lifecycleDialog = page.getByRole("dialog", {
        name: "Версії та публікація схеми",
      });
      await expect(lifecycleDialog).toBeVisible();
      await expect(
        lifecycleDialog.getByRole("button", { name: "Опублікувати поточну чернетку" }),
      ).toBeHidden();
      await lifecycleDialog.getByRole("button", { name: "Закрити версії схеми" }).click();

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

  await test.step("publish the first valid sensor placement as engineer and persist verified actor audit", async () => {
    const context = await authenticatedContext(browser, tokens.engineer);
    const page = await context.newPage();
    try {
      await openEquipment(page);
      await expectAccessRole(page, "engineer");

      const imageUploadPromise = page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/v1/equipment/${equipmentId}/images`,
      );
      const imageAttachPromise = page.waitForResponse(
        (response) =>
          response.request().method() === "PUT" &&
          new URL(response.url()).pathname === `/api/v1/equipment/${equipmentId}/layout/draft`,
      );
      await page.getByLabel("Вибрати production-фото обладнання").setInputFiles({
        name: "security-acceptance.png",
        mimeType: "image/png",
        buffer: equipmentPhoto,
      });
      expect((await imageUploadPromise).status()).toBe(201);
      expect((await imageAttachPromise).status()).toBe(200);

      const attachedDraft = await context.request.get(
        `${apiBaseUrl}/api/v1/equipment/${equipmentId}/layout/draft`,
        { headers: apiHeaders(tokens.engineer) },
      );
      expect(attachedDraft.status()).toBe(200);
      expect(attachedDraft.headers().etag).toBe('W/"layout-draft-v2"');
      const attachedDraftBody = (await attachedDraft.json()) as {
        image: { id: string };
        placements: unknown[];
      };
      expect(attachedDraftBody.placements).toEqual([]);

      const positionedDraft = await context.request.put(
        `${apiBaseUrl}/api/v1/equipment/${equipmentId}/layout/draft`,
        {
          headers: {
            ...apiHeaders(tokens.engineer),
            "If-Match": attachedDraft.headers().etag,
          },
          data: {
            image_id: attachedDraftBody.image.id,
            placements: [{ sensor_id: "security-sensor-01", x: 0.5, y: 0.5 }],
          },
        },
      );
      expect(positionedDraft.status()).toBe(200);
      expect(positionedDraft.headers().etag).toBe('W/"layout-draft-v3"');

      await page.reload({ waitUntil: "networkidle" });
      await expect(page.locator("#layout-editor").getByText("Чернетка v3", { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Відкрити версії та публікацію схеми" }).click();
      const lifecycleDialog = page.getByRole("dialog", {
        name: "Версії та публікація схеми",
      });
      await expect(lifecycleDialog).toBeVisible();
      const publishPromise = page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/v1/equipment/${equipmentId}/layout/publish`,
      );
      await lifecycleDialog.getByRole("button", { name: "Опублікувати поточну чернетку" }).click();
      expect((await publishPromise).status()).toBe(201);
      await expect(lifecycleDialog.getByText("Ревізія r1", { exact: true })).toBeVisible();

      const historyResponse = await context.request.get(
        `${apiBaseUrl}/api/v1/equipment/${equipmentId}/layout/history`,
        { headers: apiHeaders(tokens.engineer) },
      );
      expect(historyResponse.status()).toBe(200);
      const history = await historyResponse.json();
      expect(history.items[0].published_by).toBe("engineer-acceptance");
      expect(history.items[0].placements).toEqual([{ sensor_id: "security-sensor-01", x: 0.5, y: 0.5 }]);

      const auditResponse = await context.request.get(
        `${apiBaseUrl}/api/v1/audit/events?entity_type=equipment_layout&entity_id=${equipmentId}`,
        { headers: apiHeaders(tokens.administrator) },
      );
      expect(auditResponse.status()).toBe(200);
      const audit = await auditResponse.json();
      const auditActions = audit.items.map((item: { action: string }) => item.action);
      expect(auditActions[0]).toBe("layout.published");
      expect(auditActions.filter((action: string) => action === "layout.draft.updated")).toHaveLength(2);
      expect(
        audit.items.every((item: { actor_subject: string }) => item.actor_subject === "engineer-acceptance"),
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
      expect((await crossOrganization.json()).detail.code).toBe("organization_membership_not_found");

      writeFileSync(
        path.join(evidenceDirectory, "security-acceptance-summary.json"),
        `${JSON.stringify(
          {
            organizationId,
            equipmentId,
            climateChamberId,
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
