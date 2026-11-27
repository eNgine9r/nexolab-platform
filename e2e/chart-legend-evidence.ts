import { mkdirSync } from "node:fs";
import path from "node:path";

import { expect, type Locator, type Page } from "@playwright/test";

/**
 * #1878: browser evidence that a chart surface uses the shared compact legend (`ChartSeriesLegend`).
 * Asserts one-line rows with the Eye/EyeOff + Focus icon buttons and no textual card buttons, then
 * saves a screenshot of the legend and of the page for the acceptance artifact.
 */
export async function captureCompactLegend(
  page: Page,
  scope: Locator,
  evidenceDirectory: string,
  name: string,
): Promise<void> {
  const legend = scope.getByTestId("chart-series-legend").first();
  await expect(legend).toBeVisible();
  const rows = legend.getByTestId("chart-series-legend-row");
  await expect(rows.first()).toBeVisible();
  await expect(legend.getByRole("button", { name: "Приховати", exact: true })).toHaveCount(0);
  await expect(legend.getByRole("button", { name: "Лише цей", exact: true })).toHaveCount(0);

  const first = rows.first();
  await expect(first.getByRole("button", { name: /^(Приховати|Показати) / })).toHaveCount(1);
  await expect(first.getByRole("button", { name: /^Лише / })).toHaveCount(1);
  // One line per series: color, name, value and both icons share a single row.
  const height = await first.evaluate((row) => row.getBoundingClientRect().height);
  expect(height).toBeLessThanOrEqual(40);

  mkdirSync(evidenceDirectory, { recursive: true });
  await legend.scrollIntoViewIfNeeded();
  await legend.screenshot({ path: path.join(evidenceDirectory, `issue-1878-legend-${name}.png`) });
  await page.screenshot({
    path: path.join(evidenceDirectory, `issue-1878-page-${name}.png`),
    fullPage: true,
  });
}
