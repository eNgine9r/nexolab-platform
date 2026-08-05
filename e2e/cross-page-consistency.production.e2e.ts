import { expect, test, type Browser } from "@playwright/test";

const organizationId = requiredEnvironment("NEXOLAB_DASHBOARD_ORGANIZATION_ID");
const viewerToken = requiredEnvironment("NEXOLAB_DASHBOARD_VIEWER_TOKEN");

async function authenticatedPage(browser: Browser) {
  const context = await browser.newContext();
  await context.addInitScript(
    ({ accessToken, organization }) => {
      if (window.location.protocol === "about:") return;
      window.sessionStorage.setItem("nexolab.acceptance.access-token", accessToken);
      window.sessionStorage.setItem("nexolab.acceptance.organization-id", organization);
    },
    { accessToken: viewerToken, organization: organizationId },
  );
  return { context, page: await context.newPage() };
}

test("keeps shared navigation truthful and canonical", async ({ browser }) => {
  const { context, page } = await authenticatedPage(browser);

  try {
    await page.goto("/", { waitUntil: "domcontentloaded" });

    const navigation = page.getByRole("navigation", { name: "Головна навігація" });
    await expect(navigation.getByRole("link", { name: "Огляд" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await expect(navigation.locator('[aria-current="page"]')).toHaveCount(1);

    const executionProfile = page.getByRole("region", { name: "Профіль виконання" });
    await expect(executionProfile).toContainText("LOCAL_LAN");
    await expect(page.getByText("Усі сервіси в нормі")).toHaveCount(0);
    await expect(page.getByText("Хмарна синхронізація")).toHaveCount(0);
    await expect(page.getByText("Synced", { exact: true })).toHaveCount(0);

    await expect(page.getByRole("link", { name: "Всі вузли" })).toHaveAttribute("href", "/nodes");
    await expect(page.getByRole("link", { name: "Всі тривоги" })).toHaveAttribute("href", "/alerts");
    await expect(page.getByRole("link", { name: "Всі сесії" })).toHaveAttribute("href", "/sessions");
    await expect(page.getByRole("link", { name: "Всі камери" })).toHaveAttribute("href", "/cameras");
    await expect(page.getByRole("button", { name: "Лабораторія 1" })).toHaveCount(0);

    await page.getByRole("link", { name: "Всі камери" }).click();
    await expect(page).toHaveURL(/\/cameras$/);
    await expect(page.getByRole("heading", { name: "Камери", exact: true })).toBeVisible();
    await expect(
      page.getByRole("navigation", { name: "Головна навігація" }).locator('[aria-current="page"]'),
    ).toHaveCount(1);
    await expect(
      page.getByRole("navigation", { name: "Головна навігація" }).getByRole("link", { name: "Камери" }),
    ).toHaveAttribute("aria-current", "page");
  } finally {
    await context.close();
  }
});

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for cross-page consistency acceptance`);
  return value;
}
