import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const equipmentId = "showcase-106-01";
const equipmentRoute = `/refrigeration/${equipmentId}`;
const apiBaseUrl = process.env.NEXT_PUBLIC_NEXOLAB_API_BASE_URL ?? "http://127.0.0.1:18082";
const evidenceDirectory = process.env.NEXOLAB_ACCEPTANCE_EVIDENCE_DIR ?? "acceptance-evidence";
const equipmentPhoto = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAABAAAAAKCAIAAAAy3EnLAAAAF0lEQVR4nGPkUbJgIAUwkaR6VMOg0QAA11IAejJlKAQAAAAASUVORK5CYII=",
  "base64",
);

type DraftPayload = {
  version: number;
  placements: Array<{ sensor_id: string; x: number; y: number }>;
  image: { id: string; content_url: string } | null;
};

type HistoryPayload = {
  items: Array<{
    revision: number;
    source_draft_version: number;
    placements: Array<{ sensor_id: string; x: number; y: number }>;
  }>;
};

type EquipmentListPayload = {
  items: Array<{ id: string; code: string; name: string }>;
};

type AuditPayload = {
  items: Array<{ action: string; entity_id: string; actor_subject: string }>;
};

function editor(page: Page) {
  return page.locator("#layout-editor");
}

function sensorMarker(page: Page, label: string) {
  return page.getByRole("button", { name: `Вибрати датчик ${label} на схемі` });
}

async function openProductionEquipment(page: Page, version: number) {
  await page.goto(equipmentRoute, { waitUntil: "networkidle" });
  await expect(page.getByText(`Чернетка v${version} · PostgreSQL`)).toBeVisible();
}

async function enterEditMode(page: Page) {
  await editor(page).getByRole("button", { name: "Редагувати схему" }).click();
  await expect(editor(page).getByText("Режим редагування")).toBeVisible();
}

test("creates and safely removes equipment through icon-first catalog actions", async ({ page }) => {
  mkdirSync(evidenceDirectory, { recursive: true });
  const name = "Вітрина acceptance №108-01";
  const code = "ACCEPTANCE-CS-108-01";

  await page.goto("/refrigeration", { waitUntil: "networkidle" });
  const addButton = page.getByRole("button", { name: "Додати холодильне обладнання" });
  await expect(addButton).toBeVisible();
  await expect(addButton).toHaveAttribute("title", "Додати холодильне обладнання");
  await addButton.click();

  await page.getByLabel(/^Назва/).fill(name);
  await page.getByLabel(/^Код обладнання/).fill(code);
  await page.getByLabel(/^Відображуване розташування/).fill("Лабораторія acceptance · Зона C");
  await page.getByLabel(/^Виробник/).fill("NEXOLAB");
  await page.getByLabel(/^Модель/).fill("NX-1250-A");
  await page.getByLabel(/^Серійний номер/).fill("NX-ACCEPTANCE-10801");
  await page.getByLabel(/^Температурний клас/).fill("3M1 (0…+5 °C)");
  await page.getByLabel(/^Кількість слотів датчиків/).fill("48");
  await page.getByRole("button", { name: "Створити", exact: true }).click();

  await expect(page.getByRole("status")).toContainText(`${name} додано до каталогу.`);
  await expect(page.getByRole("heading", { name })).toBeVisible();

  const openLink = page.getByRole("link", { name: `Відкрити ${name}` });
  await expect(openLink).toHaveAttribute("title", "Відкрити");
  const href = await openLink.getAttribute("href");
  expect(href).toMatch(/^\/refrigeration\/[0-9a-f-]{36}$/);
  const createdEquipmentId = href?.split("/").at(-1);
  expect(createdEquipmentId).toBeTruthy();

  const deleteButton = page.getByRole("button", { name: `Видалити ${name}` });
  await expect(deleteButton).toHaveAttribute("title", `Видалити ${name}`);
  await deleteButton.click();
  const confirmation = page.getByRole("alertdialog");
  await expect(confirmation).toContainText(name);
  await expect(confirmation).toContainText("Історичні схеми та аудит залишаться збереженими");
  await confirmation.getByRole("button", { name: "Видалити", exact: true }).click();

  await expect(page.getByRole("status")).toContainText(`${name} видалено з каталогу.`);
  await expect(page.getByRole("heading", { name })).toHaveCount(0);

  const listResponse = await page.request.get(`${apiBaseUrl}/api/v1/equipment`);
  expect(listResponse.status()).toBe(200);
  const list = (await listResponse.json()) as EquipmentListPayload;
  expect(list.items.some((item) => item.id === createdEquipmentId)).toBe(false);

  const deletedResponse = await page.request.get(
    `${apiBaseUrl}/api/v1/equipment/${createdEquipmentId}`,
  );
  expect(deletedResponse.status()).toBe(404);

  const draftResponse = await page.request.get(
    `${apiBaseUrl}/api/v1/equipment/${createdEquipmentId}/layout/draft`,
  );
  expect(draftResponse.status()).toBe(200);
  const preservedDraft = (await draftResponse.json()) as DraftPayload;
  expect(preservedDraft.version).toBe(1);
  expect(preservedDraft.placements).toEqual([]);

  const auditResponse = await page.request.get(
    `${apiBaseUrl}/api/v1/audit/events?entity_type=refrigeration_equipment&entity_id=${createdEquipmentId}`,
  );
  expect(auditResponse.status()).toBe(200);
  const audit = (await auditResponse.json()) as AuditPayload;
  expect(audit.items.map((item) => item.action)).toEqual([
    "equipment.deleted",
    "equipment.created",
  ]);
  expect(audit.items.every((item) => item.actor_subject === "development-system")).toBe(true);

  await page.screenshot({
    path: path.join(evidenceDirectory, "equipment-catalog-after-safe-delete.png"),
    fullPage: true,
  });
});

test("persists, publishes and recovers a parallel stale-writer conflict", async ({ browser }) => {
  mkdirSync(evidenceDirectory, { recursive: true });

  const operatorA = await browser.newContext();
  const operatorB = await browser.newContext();
  const pageA = await operatorA.newPage();
  const pageB = await operatorB.newPage();

  try {
    await test.step("verify sidebar shell, enlarged canvas and versioned sensor assignment", async () => {
      await openProductionEquipment(pageA, 1);

      await expect(pageA.getByRole("link", { name: "Холодильне обладнання" })).toHaveAttribute(
        "href",
        "/refrigeration",
      );
      const canvasWorkspace = pageA.getByTestId("equipment-image-workspace");
      await expect(canvasWorkspace).toHaveAttribute("data-expanded", "false");
      await pageA.getByRole("button", { name: "Збільшити підкладку" }).click();
      await expect(canvasWorkspace).toHaveAttribute("data-expanded", "true");

      const candidate = pageA.getByRole("combobox", { name: "Датчик зі списку" });
      await candidate.selectOption({ index: 0 });
      await expect(pageA.getByRole("button", { name: "Додати", exact: true })).toBeEnabled();
      await pageA.getByRole("button", { name: "Додати", exact: true }).click();

      await expect(pageA.getByText(/додано на підкладку/)).toBeVisible();
      await expect(pageA.getByText("Чернетка v2 · PostgreSQL")).toBeVisible();
      await expect(editor(pageA).getByText("Режим редагування")).toBeVisible();
      await editor(pageA).getByRole("button", { name: "Скасувати", exact: true }).click();
      await expect(editor(pageA).getByText("Режим перегляду")).toBeVisible();

      await expect(pageA.getByRole("button", { name: "Замінити", exact: true })).toBeEnabled();
      await candidate.selectOption({ index: 0 });
      await pageA.getByRole("button", { name: "Замінити", exact: true }).click();

      await expect(pageA.getByText(/замінено на/)).toBeVisible();
      await expect(pageA.getByText("Чернетка v3 · PostgreSQL")).toBeVisible();
    });

    await test.step("upload a real image and verify its MinIO signed URL", async () => {
      await pageA.getByLabel("Вибрати production-фото обладнання").setInputFiles({
        name: "showcase-acceptance.png",
        mimeType: "image/png",
        buffer: equipmentPhoto,
      });

      await expect(pageA.getByText(/завантажено та прив’язано до чернетки v4/)).toBeVisible();
      await expect(pageA.getByText("Чернетка v4 · PostgreSQL")).toBeVisible();

      const image = pageA.locator(`img[alt="Фото обладнання ${equipmentId}"]`).first();
      await expect(image).toBeVisible();
      const signedUrl = await image.getAttribute("src");
      expect(signedUrl).not.toBeNull();

      const parsedSignedUrl = new URL(signedUrl ?? "");
      expect(parsedSignedUrl.origin).toBe(process.env.OBJECT_STORAGE_PUBLIC_ENDPOINT_URL);
      expect(parsedSignedUrl.searchParams.has("X-Amz-Signature")).toBe(true);
      expect(parsedSignedUrl.searchParams.has("X-Amz-Expires")).toBe(true);

      const signedResponse = await operatorA.request.get(parsedSignedUrl.toString());
      expect(signedResponse.status()).toBe(200);
      expect(signedResponse.headers()["content-type"]).toContain("image/png");

      writeFileSync(
        path.join(evidenceDirectory, "signed-image.json"),
        `${JSON.stringify(
          {
            origin: parsedSignedUrl.origin,
            pathname: parsedSignedUrl.pathname,
            queryParameters: [...parsedSignedUrl.searchParams.keys()].sort(),
            status: signedResponse.status(),
            contentType: signedResponse.headers()["content-type"],
          },
          null,
          2,
        )}\n`,
      );
    });

    await test.step("seed all sensor placements through the production editor and publish r1", async () => {
      await enterEditMode(pageA);
      await editor(pageA).getByRole("button", { name: "Скинути позиції" }).click();
      await expect(editor(pageA).getByText("Незбережені зміни")).toBeVisible();
      await editor(pageA).getByRole("button", { name: "Зберегти чернетку" }).click();

      await expect(pageA.getByText("Чернетку схеми збережено · версія 5")).toBeVisible();
      await expect(pageA.getByText("Чернетка v5 · PostgreSQL")).toBeVisible();

      await pageA.getByRole("button", { name: "Опублікувати поточну чернетку" }).click();
      await expect(pageA.getByText("Опубліковано ревізію r1.")).toBeVisible();
      await expect(pageA.getByText("Чернетка v6 · PostgreSQL")).toBeVisible();
      await expect(pageA.getByText("Ревізія r1")).toBeVisible();
      await expect(pageA.getByText("showcase-acceptance.png").first()).toBeVisible();
    });

    await test.step("run two isolated operators against the same draft version", async () => {
      await openProductionEquipment(pageB, 6);
      await enterEditMode(pageA);
      await enterEditMode(pageB);

      const markerA = sensorMarker(pageA, "01F");
      const markerB = sensorMarker(pageB, "01F");
      await expect(markerA).toBeVisible();
      await expect(markerB).toBeVisible();

      await markerA.press("ArrowRight");
      await markerB.press("ArrowLeft");
      const winningX = await markerA.getAttribute("data-x");
      const losingLocalX = await markerB.getAttribute("data-x");
      expect(winningX).not.toBeNull();
      expect(losingLocalX).not.toBeNull();
      expect(winningX).not.toBe(losingLocalX);

      await editor(pageA).getByRole("button", { name: "Зберегти чернетку" }).click();
      await expect(pageA.getByText("Чернетку схеми збережено · версія 7")).toBeVisible();

      await editor(pageB).getByRole("button", { name: "Зберегти чернетку" }).click();
      await expect(pageB.getByText("End-to-end конфлікт версій")).toBeVisible();
      await expect(pageB.getByText(/очікувала v6, але сервер уже зберігає v7/)).toBeVisible();
      await expect(markerB).toHaveAttribute("data-x", losingLocalX ?? "");

      await pageB.screenshot({
        path: path.join(evidenceDirectory, "conflict-local-state-preserved.png"),
        fullPage: true,
      });

      pageB.once("dialog", (dialog) => void dialog.accept());
      await pageB.getByRole("button", { name: "Завантажити серверну v7" }).click();
      await expect(pageB.getByText("Завантажено серверну чернетку v7.")).toBeVisible();
      await expect(editor(pageB).getByText("Режим перегляду")).toBeVisible();
      await expect(sensorMarker(pageB, "01F")).toHaveAttribute("data-x", winningX ?? "");

      await pageB.screenshot({
        path: path.join(evidenceDirectory, "conflict-server-version-reloaded.png"),
        fullPage: true,
      });
    });

    await test.step("verify final PostgreSQL-backed API state", async () => {
      const draftResponse = await operatorA.request.get(
        `${apiBaseUrl}/api/v1/equipment/${equipmentId}/layout/draft`,
      );
      expect(draftResponse.status()).toBe(200);
      expect(draftResponse.headers().etag).toBe('W/"layout-draft-v7"');
      const draft = (await draftResponse.json()) as DraftPayload;
      expect(draft.version).toBe(7);
      expect(draft.placements).toHaveLength(48);
      expect(draft.image).not.toBeNull();

      const historyResponse = await operatorA.request.get(
        `${apiBaseUrl}/api/v1/equipment/${equipmentId}/layout/history`,
      );
      expect(historyResponse.status()).toBe(200);
      const history = (await historyResponse.json()) as HistoryPayload;
      expect(history.items).toHaveLength(1);
      expect(history.items[0]).toMatchObject({
        revision: 1,
        source_draft_version: 5,
      });
      expect(history.items[0]?.placements).toHaveLength(48);

      writeFileSync(
        path.join(evidenceDirectory, "browser-acceptance-summary.json"),
        `${JSON.stringify(
          {
            equipmentId,
            finalDraftVersion: draft.version,
            draftPlacementCount: draft.placements.length,
            publishedRevision: history.items[0]?.revision,
            publishedSourceDraftVersion: history.items[0]?.source_draft_version,
            publishedPlacementCount: history.items[0]?.placements.length,
          },
          null,
          2,
        )}\n`,
      );
    });
  } finally {
    await operatorB.close();
    await operatorA.close();
  }
});
