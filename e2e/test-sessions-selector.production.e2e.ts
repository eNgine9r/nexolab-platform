import { expect, test, type Browser, type BrowserContext } from "@playwright/test";

const organizationId = requiredEnvironment("NEXOLAB_SESSIONS_ORGANIZATION_ID");
const engineerToken = requiredEnvironment("NEXOLAB_SESSIONS_ENGINEER_A_TOKEN");
const apiBaseUrl = requiredEnvironment("NEXT_PUBLIC_NEXOLAB_API_BASE_URL");

function headers(): Record<string, string> {
  return {
    Authorization: `Bearer ${engineerToken}`,
    "X-Organization-ID": organizationId,
    Accept: "application/json",
  };
}

async function authenticatedContext(browser: Browser): Promise<BrowserContext> {
  const context = await browser.newContext({ viewport: { width: 360, height: 800 } });
  await context.addInitScript(
    ({ accessToken, organization }) => {
      if (window.location.protocol === "about:") return;
      window.sessionStorage.setItem("nexolab.acceptance.access-token", accessToken);
      window.sessionStorage.setItem("nexolab.acceptance.organization-id", organization);
    },
    { accessToken: engineerToken, organization: organizationId },
  );
  return context;
}

const inventoryFixture = {
  items: [
    {
      key: "106-03|temperature.probe",
      channel_ref_id: "sessions-selector-106-03",
      node_id: "edge-01",
      equipment_id: "K106",
      equipment_name: "K106",
      climate_chamber_id: "sessions-selector-chamber",
      climate_chamber_code: "LAB-SELECTOR",
      climate_chamber_name: "Selector acceptance laboratory",
      equipment_type: "temperature_controller",
      laboratory: "Selector acceptance laboratory",
      zone: "Test zone",
      channel_id: "106-03",
      channel_name: "Probe 106-03",
      metric: "temperature.probe",
      native_unit: "degC",
      source: "sessions-selector-browser-fixture",
      quality: "valid",
      alarm: null,
      latest: null,
    },
    {
      key: "106-99|temperature.probe",
      channel_ref_id: "sessions-selector-unsupported",
      node_id: "edge-01",
      equipment_id: "K106",
      equipment_name: "K106",
      climate_chamber_id: "sessions-selector-chamber",
      climate_chamber_code: "LAB-SELECTOR",
      climate_chamber_name: "Selector acceptance laboratory",
      equipment_type: "temperature_controller",
      laboratory: "Selector acceptance laboratory",
      zone: "Test zone",
      channel_id: "106-99",
      channel_name: "Unsupported probe 106-99",
      metric: "temperature.probe",
      native_unit: "degC",
      source: "sessions-selector-browser-fixture",
      quality: "valid",
      alarm: null,
      latest: null,
    },
  ],
  total: 2,
  limit: 500,
  offset: 0,
  has_more: false,
};

test("creates a Test Sessions draft with exactly the canonical selector subset", async ({
  browser,
  request,
}) => {
  const contract = await request.get(`${apiBaseUrl}/api/v1/sessions/binding-options/production`, {
    headers: headers(),
  });
  expect(contract.status()).toBe(200);
  expect(await contract.json()).toHaveLength(34);

  const context = await authenticatedContext(browser);
  const page = await context.newPage();
  try {
    await page.route("**/api/v1/live-dashboards/channel-inventory?**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(inventoryFixture),
      });
    });

    await page.goto("/sessions/new", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Замовник *").fill("NEXOLAB Selector Acceptance");
    await page.getByRole("button", { name: "Далі" }).click();

    await page.getByLabel("Модель *").fill("Selector fixture model");
    await page.getByLabel("Серійний номер *").fill(`SEL-${Date.now()}`);
    await page.getByRole("button", { name: "Далі" }).click();

    await page.getByRole("button", { name: "Далі" }).click();
    await expect(page.getByText("Validated session telemetry", { exact: true })).toBeVisible();

    const selectionCount = page.getByTestId("telemetry-selection-count");
    await expect(selectionCount).toContainText("Обрано 0");

    const search = page.getByRole("searchbox", { name: "Пошук" });
    await search.fill("106-99");
    await expect(page.getByText("Точок телеметрії не знайдено", { exact: true })).toBeVisible();

    await search.fill("106-03");
    const point = page.getByRole("treeitem").filter({ hasText: "Probe 106-03" });
    await expect(point).toHaveCount(1);
    await point.click();
    await expect(selectionCount).toContainText("Обрано 1");
    await page.getByRole("button", { name: "Підтвердити вибір" }).click();

    const mobileOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(mobileOverflow).toBeLessThanOrEqual(1);

    await page.setViewportSize({ width: 1440, height: 1000 });
    const desktopOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(desktopOverflow).toBeLessThanOrEqual(1);

    await page.getByRole("button", { name: "Далі" }).click();
    await page.getByRole("button", { name: "Назад" }).click();
    await expect(page.getByTestId("telemetry-selection-count")).toContainText("Обрано 1");
    await page.getByRole("button", { name: "Далі" }).click();

    for (let index = 0; index < 3; index += 1) {
      await page.getByRole("button", { name: "Далі" }).click();
    }

    await expect(page.getByText("1 selected validated series", { exact: true })).toBeVisible();
    await expect(page.getByText("No fallback to the full 34-series contract", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Створити реальний draft" }).click();
    await page.waitForURL(/\/sessions\/[0-9a-f-]{36}$/);
    const sessionId = page.url().split("/").pop();
    expect(sessionId).toBeTruthy();

    const configuration = await request.get(`${apiBaseUrl}/api/v1/sessions/${sessionId}/configuration`, {
      headers: headers(),
    });
    expect(configuration.status()).toBe(200);
    const body = await configuration.json();
    expect(body.bindings).toHaveLength(1);
    expect(body.bindings[0]).toMatchObject({
      node_id: "edge-01",
      equipment_id: "K106",
      channel_id: "106-03",
      metric: "temperature.probe",
      unit: "degC",
    });
    expect(body.session.metadata_payload.telemetry_selection_count).toBe(1);
  } finally {
    await context.close();
  }
});

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for test sessions selector acceptance`);
  return value;
}
