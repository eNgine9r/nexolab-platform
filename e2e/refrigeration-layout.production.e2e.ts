import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const equipmentId = "showcase-106-01";
const equipmentRoute = `/refrigeration/${equipmentId}`;
const apiBaseUrl = process.env.NEXT_PUBLIC_NEXOLAB_API_BASE_URL ?? "http://127.0.0.1:18082";
const evidenceDirectory = process.env.NEXOLAB_ACCEPTANCE_EVIDENCE_DIR ?? "acceptance-evidence";
const equipmentPhoto = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZlZsAAAAASUVORK5CYII=",
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

test("persists, publishes and recovers a parallel stale-writer conflict", async ({ browser }) => {
  mkdirSync(evidenceDirectory, { recursive: true });

  const operatorA = await browser.newContext();
  const operatorB = await browser.newContext();
  const pageA = await operatorA.newPage();
  const pageB = await operatorB.newPage();

  try {
    await test.step("upload a real image and verify its MinIO signed URL", async () => {
      await openProductionEquipment(pageA, 1);

      await pageA.getByLabel("Вибрати production-фото обладнання").setInputFiles({
        name: "showcase-acceptance.png",
        mimeType: "image/png",
        buffer: equipmentPhoto,
      });

      await expect(pageA.getByText(/завантажено та прив’язано до чернетки v2/)).toBeVisible();
      await expect(pageA.getByText("Чернетка v2 · PostgreSQL")).toBeVisible();

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

      await expect(pageA.getByText("Чернетку схеми збережено · версія 3")).toBeVisible();
      await expect(pageA.getByText("Чернетка v3 · PostgreSQL")).toBeVisible();

      await pageA.getByRole("button", { name: "Опублікувати поточну чернетку" }).click();
      await expect(pageA.getByText("Опубліковано ревізію r1.")).toBeVisible();
      await expect(pageA.getByText("Чернетка v4 · PostgreSQL")).toBeVisible();
      await expect(pageA.getByText("Ревізія r1")).toBeVisible();
      await expect(pageA.getByText("showcase-acceptance.png").first()).toBeVisible();
    });

    await test.step("run two isolated operators against the same draft version", async () => {
      await openProductionEquipment(pageB, 4);
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
      await expect(pageA.getByText("Чернетку схеми збережено · версія 5")).toBeVisible();

      await editor(pageB).getByRole("button", { name: "Зберегти чернетку" }).click();
      await expect(pageB.getByText("End-to-end конфлікт версій")).toBeVisible();
      await expect(pageB.getByText(/очікувала v4, але сервер уже зберігає v5/)).toBeVisible();
      await expect(markerB).toHaveAttribute("data-x", losingLocalX ?? "");

      await pageB.screenshot({
        path: path.join(evidenceDirectory, "conflict-local-state-preserved.png"),
        fullPage: true,
      });

      pageB.once("dialog", (dialog) => void dialog.accept());
      await pageB.getByRole("button", { name: "Завантажити серверну v5" }).click();
      await expect(pageB.getByText("Завантажено серверну чернетку v5.")).toBeVisible();
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
      expect(draftResponse.headers().etag).toBe('W/"layout-draft-v5"');
      const draft = (await draftResponse.json()) as DraftPayload;
      expect(draft.version).toBe(5);
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
        source_draft_version: 3,
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
