import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const apiBaseUrl = process.env.NEXT_PUBLIC_NEXOLAB_API_BASE_URL ?? "http://127.0.0.1:18082";
const webBaseUrl = process.env.NEXOLAB_ACCEPTANCE_WEB_URL ?? "http://127.0.0.1:13000";
const evidenceDirectory = process.env.NEXOLAB_ACCEPTANCE_EVIDENCE_DIR ?? "acceptance-evidence";
const climateChamberId = "kk2";
const climateChamberName = "Кліматична камера №2 · KK2";
const channelIds = {
  power: "KK2-DIXELL-101-CH1",
  temperatureOne: "KK2-DIXELL-101-CH3",
  temperatureTwo: "KK2-DIXELL-101-CH2",
} as const;
const equipmentPhoto = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAABAAAAAKCAIAAAAy3EnLAAAAF0lEQVR4nGPkUbJgIAUwkaR6VMOg0QAA11IAejJlKAQAAAAASUVORK5CYII=",
  "base64",
);
const oversizedImage = Buffer.alloc(1536 * 1024 + 1, 0);
const imageLimitMessage =
  "Розмір зображення перевищує допустимі 1,5 МБ. Стисніть файл або завантажте інше зображення.";

type EquipmentPayload = {
  id: string;
  code: string;
  name: string;
  node_id: string | null;
  version: number;
};

type EquipmentListPayload = {
  items: EquipmentPayload[];
};

type BindingPayload = {
  channel_id: string;
  slot_key: string;
  label: string;
  side: "front" | "rear";
  shelf: number;
  position: number;
};

type BindingListPayload = {
  items: BindingPayload[];
};

type DraftPayload = {
  version: number;
  placements: Array<{ sensor_id: string; x: number; y: number }>;
  image: { id: string; original_filename: string; content_url: string } | null;
};

type HistoryPayload = {
  items: Array<{
    revision: number;
    source_draft_version: number;
    placements: Array<{ sensor_id: string; x: number; y: number }>;
  }>;
};

type ImageListPayload = {
  items: Array<{ id: string; original_filename: string }>;
};

type AuditPayload = {
  items: Array<{ action: string; entity_id: string; actor_subject: string }>;
};

function absoluteRoute(route: string): string {
  return `${webBaseUrl}${route}`;
}

function editor(page: Page) {
  return page.locator("#layout-editor");
}

function sensorMarker(page: Page, label: string) {
  return page.getByRole("button", { name: `Вибрати датчик ${label} на схемі` });
}

function sensorConfigurationPath(equipmentId: string): string {
  return `/api/v1/equipment/${equipmentId}/sensor-configuration`;
}

async function chooseClimateChamber(page: Page): Promise<void> {
  const selector = page.getByLabel(/^Кліматична камера/);
  await expect(selector).toContainText(climateChamberName);
  await selector.selectOption(climateChamberId);
  const channelSummary = page.getByText(/Температурні канали:/);
  await expect(channelSummary).toBeVisible();
  await expect(channelSummary).toContainText("84");
  await expect(page.getByText(/Dixell:/)).toContainText("14");
  await expect(page.getByText(/Лічильники:/)).toContainText("0");
  await expect(
    page.getByText(
      "До цієї кліматичної камери лічильники електроенергії ще не підключені.",
      { exact: true },
    ),
  ).toBeVisible();
}

async function createEquipmentViaApi(
  request: APIRequestContext,
  options: { code: string; name: string; serialNumber: string; totalSensors?: number },
): Promise<EquipmentPayload> {
  const response = await request.post(`${apiBaseUrl}/api/v1/equipment`, {
    headers: { "X-Audit-Reason": "Refrigeration browser camera-scoped fixture" },
    data: {
      code: options.code,
      name: options.name,
      location: "Лабораторія acceptance · КК2",
      laboratory: "Лабораторія acceptance",
      zone: "КК2",
      node_id: climateChamberId,
      equipment_type: "Холодильна вітрина",
      manufacturer: "NEXOLAB",
      model: "NX-CAMERA-SCOPED",
      serial_number: options.serialNumber,
      temperature_class: "3M1 (0…+5 °C)",
      installed_at: "2026-07-29",
      serviced_at: null,
      lifecycle_status: "active",
      total_sensors: options.totalSensors ?? 4,
    },
  });
  expect(response.status()).toBe(201);
  expect(response.headers().etag).toBe('W/"equipment-v1"');
  return (await response.json()) as EquipmentPayload;
}

async function openProductionEquipment(
  page: Page,
  equipment: EquipmentPayload,
  draftVersion: number,
) {
  await page.goto(absoluteRoute(`/refrigeration/${equipment.id}`), {
    waitUntil: "networkidle",
  });
  await expect(page.getByRole("heading", { name: equipment.name })).toBeVisible();
  await expect(editor(page).getByText(`Чернетка v${draftVersion}`, { exact: true })).toBeVisible();
  await expect(page.getByText(`Камера ${climateChamberId}`, { exact: true }).first()).toBeVisible();
}

async function enterEditMode(page: Page) {
  await editor(page).getByRole("button", { name: "Редагувати схему та датчики" }).click();
  await expect(
    editor(page).getByRole("region", {
      name: "Редагування складу датчиків кліматичної камери",
    }),
  ).toBeVisible();
  await expect(editor(page).getByRole("button", { name: "Зберегти всі зміни" })).toBeVisible();
}

async function addChannel(page: Page, channelId: string) {
  const selector = editor(page).getByLabel("Доступний датчик кліматичної камери");
  await expect(selector.locator(`option[value="${channelId}"]`)).toHaveCount(1);
  await selector.selectOption(channelId);
  await editor(page)
    .getByRole("button", { name: "Додати вибраний датчик на підкладку" })
    .click();
}

async function readDraft(request: APIRequestContext, equipmentId: string): Promise<DraftPayload> {
  const response = await request.get(
    `${apiBaseUrl}/api/v1/equipment/${equipmentId}/layout/draft`,
  );
  expect(response.status()).toBe(200);
  return (await response.json()) as DraftPayload;
}

async function readBindings(
  request: APIRequestContext,
  equipmentId: string,
): Promise<BindingListPayload> {
  const response = await request.get(
    `${apiBaseUrl}/api/v1/equipment/${equipmentId}/sensor-bindings`,
  );
  expect(response.status()).toBe(200);
  return (await response.json()) as BindingListPayload;
}

test("requires a climate chamber before creating or copying refrigeration equipment", async ({
  page,
}) => {
  mkdirSync(evidenceDirectory, { recursive: true });
  const name = "Вітрина acceptance №108-01";
  const code = "ACCEPTANCE-CS-108-01";
  const copyName = `${name} — копія`;
  const copyCode = `${code}-COPY`;

  await page.goto(absoluteRoute("/refrigeration"), { waitUntil: "networkidle" });
  const addButton = page.getByRole("button", { name: "Додати холодильне обладнання" });
  await expect(addButton).toBeVisible();
  await expect(addButton).toHaveAttribute("title", "Додати холодильне обладнання");
  await addButton.click();

  await expect(page.getByText(/Спочатку оберіть кліматичну камеру/)).toBeVisible();
  await expect(page.getByLabel(/^Назва/)).toBeDisabled();
  await chooseClimateChamber(page);
  await expect(page.getByLabel(/^Назва/)).toBeEnabled();

  await page.getByLabel(/^Назва/).fill(name);
  await page.getByLabel(/^Код обладнання/).fill(code);
  await page.getByLabel(/^Лабораторія/).fill("Лабораторія acceptance");
  await page.getByLabel(/^Зона/).fill("КК2");
  await page
    .getByLabel(/^Відображуване розташування/)
    .fill("Лабораторія acceptance · КК2");
  await page.getByLabel(/^Виробник/).fill("NEXOLAB");
  await page.getByLabel(/^Модель/).fill("NX-1250-A");
  await page.getByLabel(/^Серійний номер/).fill("NX-ACCEPTANCE-10801");
  await page.getByLabel(/^Температурний клас/).fill("3M1 (0…+5 °C)");
  await page.getByLabel(/^Кількість слотів датчиків/).fill("4");
  const createButton = page.getByRole("button", { name: "Створити", exact: true });
  await expect(createButton).toBeEnabled();
  await createButton.click();

  await expect(page.getByRole("status")).toContainText(`${name} додано до каталогу.`);
  await expect(page.getByRole("heading", { name })).toBeVisible();
  await expect(page.getByText("Кліматична камера №2", { exact: true })).toBeVisible();

  const openLink = page.getByRole("link", { name: `Відкрити ${name}` });
  await expect(openLink).toHaveAttribute("title", "Відкрити");
  const href = await openLink.getAttribute("href");
  expect(href).toMatch(/^\/refrigeration\/[0-9a-f-]{36}$/);
  const createdEquipmentId = href?.split("/").at(-1);
  expect(createdEquipmentId).toBeTruthy();

  const copyButton = page.getByRole("button", { name: `Копіювати ${name}` });
  await expect(copyButton).toHaveAttribute("title", `Копіювати ${name}`);
  await copyButton.click();
  await expect(
    page.getByRole("heading", { name: "Копія холодильного обладнання" }),
  ).toBeVisible();
  await expect(page.getByLabel(/^Кліматична камера/)).toHaveValue("");
  await expect(page.getByLabel(/^Назва/)).toBeDisabled();
  await expect(
    page.getByText(/датчики, фото, схеми, історія й аудит не копіюються/i),
  ).toBeVisible();

  await chooseClimateChamber(page);
  await expect(page.getByLabel(/^Назва/)).toHaveValue(copyName);
  await expect(page.getByLabel(/^Код обладнання/)).toHaveValue(copyCode);
  await expect(page.getByLabel(/^Серійний номер/)).toHaveValue("");
  await page.getByLabel(/^Серійний номер/).fill("NX-ACCEPTANCE-COPY-10801");
  await page.getByRole("button", { name: "Створити копію", exact: true }).click();

  await expect(page.getByRole("status")).toContainText(
    `${copyName} створено як незалежну копію.`,
  );
  await expect(page.getByRole("heading", { name: copyName })).toBeVisible();
  const copyOpenLink = page.getByRole("link", { name: `Відкрити ${copyName}` });
  const copyHref = await copyOpenLink.getAttribute("href");
  expect(copyHref).toMatch(/^\/refrigeration\/[0-9a-f-]{36}$/);
  const copiedEquipmentId = copyHref?.split("/").at(-1);
  expect(copiedEquipmentId).toBeTruthy();
  expect(copiedEquipmentId).not.toBe(createdEquipmentId);

  await page.getByRole("button", { name: `Видалити ${copyName}` }).click();
  await page
    .getByRole("alertdialog")
    .getByRole("button", { name: "Видалити", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText(
    `${copyName} видалено з каталогу.`,
  );

  const deleteButton = page.getByRole("button", { name: `Видалити ${name}` });
  await expect(deleteButton).toHaveAttribute("title", `Видалити ${name}`);
  await deleteButton.click();
  const confirmation = page.getByRole("alertdialog");
  await expect(confirmation).toContainText(name);
  await expect(confirmation).toContainText(
    "Історичні схеми та аудит залишаться збереженими",
  );
  await confirmation.getByRole("button", { name: "Видалити", exact: true }).click();

  await expect(page.getByRole("status")).toContainText(`${name} видалено з каталогу.`);
  await expect(page.getByRole("heading", { name })).toHaveCount(0);

  const listResponse = await page.request.get(`${apiBaseUrl}/api/v1/equipment`);
  expect(listResponse.status()).toBe(200);
  const list = (await listResponse.json()) as EquipmentListPayload;
  expect(list.items.some((item) => item.id === createdEquipmentId)).toBe(false);
  expect(list.items.some((item) => item.id === copiedEquipmentId)).toBe(false);

  const deletedResponse = await page.request.get(
    `${apiBaseUrl}/api/v1/equipment/${createdEquipmentId}`,
  );
  expect(deletedResponse.status()).toBe(404);

  const preservedDraft = await readDraft(page.request, createdEquipmentId ?? "");
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
    path: path.join(evidenceDirectory, "camera-scoped-catalog-after-safe-delete.png"),
    fullPage: true,
  });
});

test("stages multiple chamber sensors and persists them in one atomic transaction", async ({
  browser,
  request,
}) => {
  mkdirSync(evidenceDirectory, { recursive: true });
  const equipment = await createEquipmentViaApi(request, {
    code: "ACCEPTANCE-CAMERA-BATCH-01",
    name: "Вітрина camera-scoped batch",
    serialNumber: "NX-CAMERA-BATCH-0001",
    totalSensors: 4,
  });

  const operatorA = await browser.newContext();
  const operatorB = await browser.newContext();
  const pageA = await operatorA.newPage();
  const pageB = await operatorB.newPage();

  try {
    await openProductionEquipment(pageA, equipment, 1);
    await openProductionEquipment(pageB, equipment, 1);

    await expect(pageA.getByText("Паспорт і стан", { exact: true })).toHaveCount(0);
    await expect(pageA.getByText("Датчики в реальному часі", { exact: true })).toHaveCount(0);
    const canvasWorkspace = pageA.getByTestId("equipment-image-workspace");
    await expect(canvasWorkspace).toHaveAttribute("data-expanded", "false");
    await pageA.getByRole("button", { name: "Збільшити підкладку" }).click();
    await expect(canvasWorkspace).toHaveAttribute("data-expanded", "true");

    await enterEditMode(pageA);
    await enterEditMode(pageB);

    await addChannel(pageB, channelIds.temperatureTwo);
    await expect(editor(pageB).getByText("Незбережені зміни")).toBeVisible();

    let configurationWrites = 0;
    pageA.on("request", (pending) => {
      if (
        pending.method() === "PUT" &&
        new URL(pending.url()).pathname === sensorConfigurationPath(equipment.id)
      ) {
        configurationWrites += 1;
      }
    });

    await addChannel(pageA, channelIds.temperatureOne);
    await addChannel(pageA, channelIds.temperatureTwo);
    expect(configurationWrites).toBe(0);

    const preSaveBindings = await readBindings(operatorA.request, equipment.id);
    const preSaveDraft = await readDraft(operatorA.request, equipment.id);
    expect(preSaveBindings.items).toEqual([]);
    expect(preSaveDraft.version).toBe(1);
    expect(preSaveDraft.placements).toEqual([]);

    await pageA.getByRole("button", { name: "Редагувати датчик 01F" }).click();
    await editor(pageA).getByLabel("Замінити канал датчика").selectOption(channelIds.power);
    await editor(pageA).getByLabel("Підпис датчика").fill("PWR-01");
    await editor(pageA).getByLabel("Полиця датчика").selectOption("2");
    await editor(pageA).getByLabel("Позиція датчика").selectOption("3");

    await pageA.getByRole("button", { name: "Редагувати датчик 02F" }).click();
    pageA.once("dialog", (dialog) => void dialog.accept());
    await editor(pageA).getByRole("button", { name: "Видалити датчик з підкладки" }).click();

    await addChannel(pageA, channelIds.temperatureOne);
    const powerMarker = sensorMarker(pageA, "PWR-01");
    await expect(powerMarker).toBeVisible();
    const powerXBefore = await powerMarker.getAttribute("data-x");
    await powerMarker.press("ArrowRight");
    const powerXAfter = await powerMarker.getAttribute("data-x");
    expect(powerXBefore).not.toBe(powerXAfter);

    const availableSelector = editor(pageA).getByLabel(
      "Доступний датчик кліматичної камери",
    );
    await expect(
      availableSelector.locator(`option[value="${channelIds.temperatureTwo}"]`),
    ).toHaveCount(1);
    await expect(
      availableSelector.locator(`option[value="${channelIds.power}"]`),
    ).toHaveCount(0);
    await expect(
      availableSelector.locator(`option[value="${channelIds.temperatureOne}"]`),
    ).toHaveCount(0);
    expect(configurationWrites).toBe(0);

    const saveResponsePromise = pageA.waitForResponse(
      (response) =>
        response.request().method() === "PUT" &&
        new URL(response.url()).pathname === sensorConfigurationPath(equipment.id),
    );
    await editor(pageA).getByRole("button", { name: "Зберегти всі зміни" }).click();
    const saveResponse = await saveResponsePromise;
    expect(saveResponse.status()).toBe(200);
    expect(configurationWrites).toBe(1);

    await expect(editor(pageA).getByText("Чернетка v2", { exact: true })).toBeVisible();
    await expect(
      editor(pageA).getByRole("button", { name: "Редагувати схему та датчики" }),
    ).toBeVisible();
    await expect(
      editor(pageA).getByRole("region", {
        name: "Редагування складу датчиків кліматичної камери",
      }),
    ).toHaveCount(0);
    await expect(pageA.getByRole("button", { name: /^Редагувати датчик/ })).toHaveCount(0);

    const equipmentResponse = await operatorA.request.get(
      `${apiBaseUrl}/api/v1/equipment/${equipment.id}`,
    );
    expect(equipmentResponse.status()).toBe(200);
    const equipmentAfterSave = (await equipmentResponse.json()) as EquipmentPayload;
    expect(equipmentAfterSave.version).toBe(2);
    expect(equipmentAfterSave.node_id).toBe(climateChamberId);

    const bindingsAfterSave = await readBindings(operatorA.request, equipment.id);
    const draftAfterSave = await readDraft(operatorA.request, equipment.id);
    expect(bindingsAfterSave.items).toHaveLength(2);
    expect(bindingsAfterSave.items.map((item) => item.channel_id).sort()).toEqual([
      channelIds.power,
      channelIds.temperatureOne,
    ]);
    expect(
      bindingsAfterSave.items.find((item) => item.channel_id === channelIds.power),
    ).toMatchObject({
      label: "PWR-01",
      side: "front",
      shelf: 2,
      position: 3,
    });
    expect(draftAfterSave.version).toBe(2);
    expect(draftAfterSave.placements).toHaveLength(2);
    expect(draftAfterSave.placements.map((item) => item.sensor_id).sort()).toEqual([
      channelIds.power,
      channelIds.temperatureOne,
    ]);

    const staleSavePromise = pageB.waitForResponse(
      (response) =>
        response.request().method() === "PUT" &&
        new URL(response.url()).pathname === sensorConfigurationPath(equipment.id),
    );
    await editor(pageB).getByRole("button", { name: "Зберегти всі зміни" }).click();
    const staleSave = await staleSavePromise;
    expect(staleSave.status()).toBe(409);
    await expect(
      editor(pageB).getByText(
        /Конфігурацію змінив інший оператор.*актуальна версія 2/,
      ),
    ).toBeVisible();

    pageB.on("dialog", (dialog) => void dialog.accept());
    await pageB.reload({ waitUntil: "networkidle" });
    await expect(editor(pageB).getByText("Чернетка v2", { exact: true })).toBeVisible();
    await expect(sensorMarker(pageB, "PWR-01")).toBeVisible();
    await expect(sensorMarker(pageB, "01F")).toBeVisible();
    await expect(pageB.getByRole("button", { name: /^Редагувати датчик/ })).toHaveCount(0);

    let imageUploadWrites = 0;
    pageA.on("request", (pending) => {
      if (
        pending.method() === "POST" &&
        new URL(pending.url()).pathname === `/api/v1/equipment/${equipment.id}/images`
      ) {
        imageUploadWrites += 1;
      }
    });

    await pageA.getByLabel("Вибрати production-фото обладнання").setInputFiles({
      name: "too-large.png",
      mimeType: "image/png",
      buffer: oversizedImage,
    });
    await expect(pageA.getByText(imageLimitMessage, { exact: true })).toBeVisible();
    expect(imageUploadWrites).toBe(0);
    expect((await readDraft(operatorA.request, equipment.id)).version).toBe(2);
    const noImagesResponse = await operatorA.request.get(
      `${apiBaseUrl}/api/v1/equipment/${equipment.id}/images`,
    );
    expect(noImagesResponse.status()).toBe(200);
    expect(((await noImagesResponse.json()) as ImageListPayload).items).toEqual([]);

    const uploadResponsePromise = pageA.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/v1/equipment/${equipment.id}/images`,
    );
    const attachResponsePromise = pageA.waitForResponse(
      (response) =>
        response.request().method() === "PUT" &&
        new URL(response.url()).pathname === `/api/v1/equipment/${equipment.id}/layout/draft`,
    );
    await pageA.getByLabel("Вибрати production-фото обладнання").setInputFiles({
      name: "showcase-acceptance.png",
      mimeType: "image/png",
      buffer: equipmentPhoto,
    });
    expect((await uploadResponsePromise).status()).toBe(201);
    expect((await attachResponsePromise).status()).toBe(200);
    expect(imageUploadWrites).toBe(1);

    await expect(editor(pageA).getByText("Чернетка v3", { exact: true })).toBeVisible();
    const image = pageA.locator(`img[alt="Фото обладнання ${equipment.id}"]`).first();
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

    const publishResponsePromise = pageA.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/v1/equipment/${equipment.id}/layout/publish`,
    );
    await pageA.getByRole("button", { name: "Опублікувати поточну чернетку" }).click();
    expect((await publishResponsePromise).status()).toBe(201);
    await expect(pageA.getByText("Ревізія r1", { exact: true })).toBeVisible();
    await expect(editor(pageA).getByText("Чернетка v4", { exact: true })).toBeVisible();

    const finalDraft = await readDraft(operatorA.request, equipment.id);
    expect(finalDraft.version).toBe(4);
    expect(finalDraft.placements).toHaveLength(2);
    expect(finalDraft.image?.original_filename).toBe("showcase-acceptance.png");

    const historyResponse = await operatorA.request.get(
      `${apiBaseUrl}/api/v1/equipment/${equipment.id}/layout/history`,
    );
    expect(historyResponse.status()).toBe(200);
    const history = (await historyResponse.json()) as HistoryPayload;
    expect(history.items).toHaveLength(1);
    expect(history.items[0]).toMatchObject({
      revision: 1,
      source_draft_version: 3,
    });
    expect(history.items[0]?.placements).toHaveLength(2);

    await pageA.screenshot({
      path: path.join(evidenceDirectory, "camera-scoped-atomic-layout.png"),
      fullPage: true,
    });
    await pageB.screenshot({
      path: path.join(evidenceDirectory, "camera-scoped-stale-writer-reloaded.png"),
      fullPage: true,
    });
    writeFileSync(
      path.join(evidenceDirectory, "browser-acceptance-summary.json"),
      `${JSON.stringify(
        {
          equipmentId: equipment.id,
          climateChamberId,
          configuredChannels: bindingsAfterSave.items.map((item) => item.channel_id).sort(),
          sensorConfigurationWrites: configurationWrites,
          staleWriterStatus: staleSave.status(),
          finalDraftVersion: finalDraft.version,
          finalPlacementCount: finalDraft.placements.length,
          publishedRevision: history.items[0]?.revision,
          publishedSourceDraftVersion: history.items[0]?.source_draft_version,
          imageUploadWrites,
          oversizedImageRejectedBeforeUpload: true,
        },
        null,
        2,
      )}\n`,
    );
  } finally {
    await Promise.allSettled([operatorB.close(), operatorA.close()]);
  }
});
