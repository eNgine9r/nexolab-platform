import fs from "node:fs/promises";
import path from "node:path";

import { expect, test } from "@playwright/test";

const evidenceDirectory =
  process.env.NEXOLAB_OBSERVABILITY_EVIDENCE_DIR ?? "test-results-observability";
const adminUser = process.env.GRAFANA_ADMIN_USER ?? "nexolab-admin";
const adminPassword = process.env.GRAFANA_ADMIN_PASSWORD;

const dashboardPath =
  "/d/nexolab-platform-overview/nexolab-platform-operations" +
  "?orgId=1&from=now-6h&to=now&timezone=browser&refresh=5s";

async function scrollToStart(locator: ReturnType<Parameters<typeof test>[1]>) {
  await locator.evaluate((element) =>
    element.scrollIntoView({ block: "start", inline: "nearest" }),
  );
}

test("operator can inspect the provisioned NEXOLAB monitoring dashboard", async ({
  page,
}) => {
  expect(adminPassword, "GRAFANA_ADMIN_PASSWORD must be provided").toBeTruthy();

  const browserErrors: string[] = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));

  await page.goto("/login", { waitUntil: "domcontentloaded" });
  await page.locator('input[name="user"]').fill(adminUser);
  await page.locator('input[name="password"]').fill(adminPassword ?? "");
  await page.locator('button[type="submit"]').click();
  await expect(page).not.toHaveURL(/\/login(?:\?|$)/);

  await page.goto(dashboardPath, { waitUntil: "domcontentloaded" });
  await expect(page).toHaveURL(/\/d\/nexolab-platform-overview\//);
  await expect(
    page.getByText("NEXOLAB · Platform Operations", { exact: true }),
  ).toBeVisible();

  const panelTitles = [
    "Telemetry Service",
    "Platform dependencies",
    "MQTT subscription",
    "PostgreSQL",
    "Queue utilization",
    "Ingestion lag",
    "Telemetry throughput",
    "Persistence and dead letters",
    "Verified backup age",
    "Bundle verification",
    "Firing alerts",
    "Alertmanager delivery evidence",
  ];
  for (const panelTitle of panelTitles) {
    await expect(page.getByText(panelTitle, { exact: true }).first()).toBeVisible();
  }

  await expect(page.getByText(/Dashboard not found/i)).toHaveCount(0);
  await expect(page.getByText(/Datasource .* not found/i)).toHaveCount(0);

  await fs.mkdir(evidenceDirectory, { recursive: true });

  const readinessSection = page.getByText("Platform readiness", { exact: true });
  await readinessSection.evaluate((element) =>
    element.scrollIntoView({ block: "start", inline: "nearest" }),
  );
  await page.waitForTimeout(1_000);
  await page.screenshot({
    path: path.join(evidenceDirectory, "grafana-platform-readiness.png"),
  });

  const recoverySection = page.getByText("Disaster recovery readiness", {
    exact: true,
  });
  await recoverySection.evaluate((element) =>
    element.scrollIntoView({ block: "start", inline: "nearest" }),
  );
  await page.waitForTimeout(1_000);
  await page.screenshot({
    path: path.join(evidenceDirectory, "grafana-disaster-recovery.png"),
  });

  const alertDeliveryPanel = page
    .getByText("Alertmanager delivery evidence", { exact: true })
    .first();
  await alertDeliveryPanel.evaluate((element) =>
    element.scrollIntoView({ block: "center", inline: "nearest" }),
  );
  await page.waitForTimeout(1_000);
  await page.screenshot({
    path: path.join(evidenceDirectory, "grafana-alert-delivery.png"),
  });

  await fs.writeFile(
    path.join(evidenceDirectory, "grafana-browser-summary.json"),
    `${JSON.stringify(
      {
        dashboardUid: "nexolab-platform-overview",
        dashboardTitle: "NEXOLAB · Platform Operations",
        panelChecks: panelTitles.length,
        screenshots: [
          "grafana-platform-readiness.png",
          "grafana-disaster-recovery.png",
          "grafana-alert-delivery.png",
        ],
        pageErrors: browserErrors,
        renderedInChromium: true,
      },
      null,
      2,
    )}\n`,
    "utf8",
  );

  expect(browserErrors).toEqual([]);
});
