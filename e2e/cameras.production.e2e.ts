import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";

const organizationId = requiredEnvironment("NEXOLAB_DASHBOARD_ORGANIZATION_ID");
const viewerToken = requiredEnvironment("NEXOLAB_DASHBOARD_VIEWER_TOKEN");
const evidenceDirectory = process.env.NEXOLAB_DASHBOARD_EVIDENCE_DIR ?? "dashboard-acceptance-evidence";

type ObservedApiRequest = {
  method: string;
  pathname: string;
};

async function authenticatedContext(browser: Browser): Promise<BrowserContext> {
  const context = await browser.newContext();
  await context.addInitScript(
    ({ accessToken, organization }) => {
      if (window.location.protocol === "about:") return;
      window.sessionStorage.setItem("nexolab.acceptance.access-token", accessToken);
      window.sessionStorage.setItem("nexolab.acceptance.organization-id", organization);
    },
    { accessToken: viewerToken, organization: organizationId },
  );
  return context;
}

function observeApiRequests(page: Page): ObservedApiRequest[] {
  const requests: ObservedApiRequest[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/v1/")) return;
    requests.push({ method: request.method(), pathname: url.pathname });
  });
  return requests;
}

test("renders truthful local Cameras without fabricated LIVE evidence or mutations", async ({ browser }) => {
  mkdirSync(evidenceDirectory, { recursive: true });
  const context = await authenticatedContext(browser);
  const page = await context.newPage();
  const requests = observeApiRequests(page);

  try {
    await page.goto("/cameras", { waitUntil: "domcontentloaded" });

    await expect(page.getByText("Viewer Acceptance", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Камери", exact: true })).toBeVisible();
    await expect(page.getByText("Камери не налаштовані", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Пошук камер")).toBeVisible();
    await expect(page.getByLabel("Фільтр стану")).toBeVisible();

    const camerasBody = await page.locator("body").innerText();
    expect(camerasBody).not.toContain(viewerToken);
    expect(camerasBody).not.toContain("admin:secret");
    expect(camerasBody).not.toContain("LIVE\n");

    await page.goto("/", { waitUntil: "domcontentloaded" });
    const cameraPanel = page.getByText("Камери не налаштовані", { exact: true });
    await expect(cameraPanel).toBeVisible();
    const cameraLink = page.getByRole("link", { name: "Відкрити стан камер" });
    await expect(cameraLink).toHaveAttribute("href", "/cameras");
    await cameraLink.click();
    await expect(page).toHaveURL(/\/cameras$/);

    expect(requests.filter((request) => request.method !== "GET")).toEqual([]);

    await page.screenshot({
      path: path.join(evidenceDirectory, "cameras-truthful-unconfigured-workspace.png"),
      fullPage: true,
    });
    writeFileSync(
      path.join(evidenceDirectory, "cameras-summary.json"),
      `${JSON.stringify(
        {
          organizationId,
          unconfiguredStateVerified: true,
          fabricatedLiveEvidenceObserved: false,
          canonicalOverviewNavigation: true,
          mutationsObserved: requests.filter((request) => request.method !== "GET").length,
          secretExposureObserved: false,
        },
        null,
        2,
      )}\n`,
    );
  } finally {
    await context.close();
  }
});

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for Cameras acceptance`);
  return value;
}
