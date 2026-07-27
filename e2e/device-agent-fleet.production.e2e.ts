import { expect, test, type Page } from "@playwright/test";

const organizationId = required("NEXOLAB_DEVICE_AGENT_FLEET_ORGANIZATION_ID");
const managerToken = required("NEXOLAB_DEVICE_AGENT_FLEET_MANAGER_TOKEN");

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

async function assertRecoveredNode(
  page: Page,
  nodeId: "edge-01" | "edge-02",
  latestOperation: "rotate" | "provision",
): Promise<void> {
  const row = page.getByTestId(`node-row-${nodeId}`);
  await expect(row).toBeVisible();
  await expect(page.getByTestId(`node-row-availability-${nodeId}`)).toHaveText("online");
  await row.click();

  await expect(page.getByTestId("node-availability")).toHaveText("Online");
  await expect(page.getByTestId("node-operational-state")).toContainText("0 events");
  await expect(page.getByTestId("node-operational-state")).toContainText("fleet-acceptance");
  await expect(page.getByTestId("node-broker-synchronization")).toContainText("Синхронізовано");
  await expect(page.getByTestId("node-broker-control")).toContainText("Client enabled");
  await expect(page.getByTestId("node-broker-control")).toContainText(`${latestOperation} · applied`);
}

test("renders two recovered secure Device Agents after outage and credential rotation", async ({ page }) => {
  await installBrowserCredentials(page);
  await page.goto("/nodes");

  await expect(page.getByTestId("nodes-workspace")).toBeVisible();
  await assertRecoveredNode(page, "edge-01", "rotate");
  await assertRecoveredNode(page, "edge-02", "provision");

  const body = page.locator("body");
  for (const forbidden of [
    "nxl_node_",
    "mqtt-password",
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
