import { expect, test, type Page } from "@playwright/test";

const organizationId = required("NEXOLAB_BROKER_CONTROL_ORGANIZATION_ID");
const managerToken = required("NEXOLAB_BROKER_CONTROL_MANAGER_TOKEN");

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

async function installBrowserCredentials(page: Page): Promise<void> {
  await page.addInitScript(
    ({ token, organization }) => {
      if (window.location.protocol === "about:") return;
      window.sessionStorage.setItem("nexolab.acceptance.access-token", token);
      window.sessionStorage.setItem("nexolab.acceptance.organization-id", organization);
      window.localStorage.setItem("nexolab.selectedOrganizationId", organization);
    },
    { token: managerToken, organization: organizationId },
  );
}

test("renders applied broker lifecycle without exposing secret fields", async ({ page }) => {
  await installBrowserCredentials(page);
  await page.goto("/nodes");

  const row = page.getByTestId("node-row-edge-01");
  await expect(row).toBeVisible();
  await row.click();

  const panel = page.getByTestId("node-broker-control");
  await expect(panel).toBeVisible();
  await expect(page.getByTestId("node-broker-synchronization")).toContainText("Синхронізовано");
  await expect(panel).toContainText("Client deleted");
  await expect(panel).toContainText("delete");
  await expect(panel).toContainText("enable");
  await expect(panel).toContainText("disable");
  await expect(panel).toContainText("rotate");
  await expect(panel).toContainText("provision");

  const body = page.locator("body");
  for (const forbidden of [
    "secret_ciphertext",
    "secret_nonce",
    "secret_key_id",
    "deduplication_key",
    "command_sha256",
  ]) {
    await expect(body).not.toContainText(forbidden);
  }
  await expect(page).toHaveURL(/\/nodes$/);
});
