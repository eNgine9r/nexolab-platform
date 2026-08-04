import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";

const organizationId = requiredEnvironment("NEXOLAB_DASHBOARD_ORGANIZATION_ID");
const viewerToken = requiredEnvironment("NEXOLAB_DASHBOARD_VIEWER_TOKEN");
const evidenceDirectory = process.env.NEXOLAB_DASHBOARD_EVIDENCE_DIR ?? "dashboard-acceptance-evidence";
const composeProject = requiredEnvironment("COMPOSE_PROJECT_NAME");
const baseCompose = requiredEnvironment("NEXOLAB_DASHBOARD_BASE_COMPOSE");
const acceptanceCompose = requiredEnvironment("NEXOLAB_DASHBOARD_ACCEPTANCE_COMPOSE");
const postgresDatabase = process.env.POSTGRES_DB?.trim() || "nexolab";
const postgresUser = process.env.POSTGRES_USER?.trim() || "nexolab";
const objectStorageEndpoint = requiredEnvironment("OBJECT_STORAGE_PUBLIC_ENDPOINT_URL");

const currentEquipmentId = "50000000-0000-4000-8000-000000000001";
const changedEquipmentId = "50000000-0000-4000-8000-000000000002";
const draftOnlyEquipmentId = "50000000-0000-4000-8000-000000000003";
const noImageEquipmentId = "50000000-0000-4000-8000-000000000004";
const failedEquipmentId = "50000000-0000-4000-8000-000000000005";

const currentImageId = "51000000-0000-4000-8000-000000000001";
const changedImageId = "51000000-0000-4000-8000-000000000002";
const draftOnlyImageId = "51000000-0000-4000-8000-000000000003";

const currentStorageKey = `equipment-images/${organizationId}/${currentImageId}.png`;
const changedStorageKey = `equipment-images/${organizationId}/${changedImageId}.png`;
const draftOnlyStorageKey = `equipment-images/${organizationId}/${draftOnlyImageId}.png`;

const fixturePng = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
  "base64",
);

type ObservedEquipmentRequest = {
  method: string;
  pathname: string;
  authorization: boolean;
  organization: string | null;
};

type SignedImageResponse = {
  pathname: string;
  queryKeys: string[];
  status: number;
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

function observeEquipmentRequests(page: Page): ObservedEquipmentRequest[] {
  const requests: ObservedEquipmentRequest[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/v1/equipment")) return;
    const headers = request.headers();
    requests.push({
      method: request.method(),
      pathname: url.pathname,
      authorization: headers.authorization?.startsWith("Bearer ") ?? false,
      organization: headers["x-organization-id"] ?? null,
    });
  });
  return requests;
}

function observeSignedImageResponses(page: Page): SignedImageResponse[] {
  const responses: SignedImageResponse[] = [];
  page.on("response", (response) => {
    if (!response.url().startsWith(objectStorageEndpoint)) return;
    const url = new URL(response.url());
    responses.push({
      pathname: url.pathname,
      queryKeys: [...url.searchParams.keys()].sort(),
      status: response.status(),
    });
  });
  return responses;
}

function composeBaseArguments(): string[] {
  return ["compose", "--project-name", composeProject, "--file", baseCompose, "--file", acceptanceCompose];
}

function composeExec(service: string, args: string[], input?: string): string {
  return execFileSync("docker", [...composeBaseArguments(), "exec", "-T", service, ...args], {
    input,
    encoding: "utf8",
    env: process.env,
    stdio: ["pipe", "pipe", "pipe"],
  });
}

function putFixtureObject(storageKey: string): void {
  execFileSync(
    "docker",
    [
      ...composeBaseArguments(),
      "run",
      "--rm",
      "--no-deps",
      "-T",
      "--entrypoint",
      "/bin/sh",
      "-e",
      `LAYOUT_OBJECT_KEY=${storageKey}`,
      "minio-init",
      "-ec",
      [
        'mc alias set acceptance http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null',
        'mc mb --ignore-existing "acceptance/$OBJECT_STORAGE_BUCKET" >/dev/null',
        "cat >/tmp/layout-fixture.png",
        'mc cp /tmp/layout-fixture.png "acceptance/$OBJECT_STORAGE_BUCKET/$LAYOUT_OBJECT_KEY" >/dev/null',
      ].join("\n"),
    ],
    {
      input: fixturePng,
      env: process.env,
      stdio: ["pipe", "pipe", "pipe"],
    },
  );
}

function seedEquipmentLayoutFixtures(): void {
  mkdirSync(evidenceDirectory, { recursive: true });
  putFixtureObject(currentStorageKey);
  putFixtureObject(changedStorageKey);
  putFixtureObject(draftOnlyStorageKey);

  const checksum = createHash("sha256").update(fixturePng).digest("hex");
  const sql = `
INSERT INTO refrigeration_equipment (
  id,
  organization_id,
  code,
  name,
  location,
  laboratory,
  zone,
  node_id,
  climate_chamber_id,
  equipment_type,
  manufacturer,
  model,
  serial_number,
  temperature_class,
  installed_at,
  serviced_at,
  lifecycle_status,
  status,
  average_temperature_c,
  min_temperature_c,
  max_temperature_c,
  online_sensors,
  total_sensors,
  active_alarms,
  last_seen_at,
  version,
  created_by,
  created_at,
  updated_at,
  deleted_by,
  deleted_at
)
VALUES
  (
    '${currentEquipmentId}', :'organization_id', 'LAY-CURRENT-01',
    'Вітрина з актуальною схемою', 'Layout Lab A · Zone Alpha', 'Layout Lab A', 'Zone Alpha',
    NULL, NULL, 'Холодильна вітрина', 'NEXOLAB', 'Catalog Current', 'CAT-CURRENT-01',
    '3M1', DATE '2026-01-10', DATE '2026-07-20', 'active', 'normal', 3.2, 2.8, 3.7,
    2, 2, 0, CURRENT_TIMESTAMP, 1, 'equipment-layouts-acceptance', CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP, NULL, NULL
  ),
  (
    '${changedEquipmentId}', :'organization_id', 'LAY-CHANGED-02',
    'Вітрина з неопублікованими змінами', 'Layout Lab A · Zone Beta', 'Layout Lab A', 'Zone Beta',
    NULL, NULL, 'Холодильна вітрина', 'NEXOLAB', 'Catalog Changed', 'CAT-CHANGED-02',
    '3M1', DATE '2026-01-11', DATE '2026-07-21', 'maintenance', 'warning', 4.1, 3.5, 4.8,
    1, 2, 0, CURRENT_TIMESTAMP, 1, 'equipment-layouts-acceptance', CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP, NULL, NULL
  ),
  (
    '${draftOnlyEquipmentId}', :'organization_id', 'LAY-DRAFT-03',
    'Вітрина лише з чернеткою', 'Layout Lab B · Zone Gamma', 'Layout Lab B', 'Zone Gamma',
    NULL, NULL, 'Холодильна вітрина', 'NEXOLAB', 'Catalog Draft', 'CAT-DRAFT-03',
    '3M2', DATE '2026-01-12', DATE '2026-07-22', 'active', 'offline', 0, 0, 0,
    0, 1, 0, NULL, 1, 'equipment-layouts-acceptance', CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP, NULL, NULL
  ),
  (
    '${noImageEquipmentId}', :'organization_id', 'LAY-NOIMAGE-04',
    'Вітрина без фото', 'Layout Lab B · Zone Delta', 'Layout Lab B', 'Zone Delta',
    NULL, NULL, 'Холодильна вітрина', 'NEXOLAB', 'Catalog No Image', 'CAT-NOIMAGE-04',
    '3M2', DATE '2026-01-13', DATE '2026-07-23', 'retired', 'offline', 0, 0, 0,
    0, 1, 0, NULL, 1, 'equipment-layouts-acceptance', CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP, NULL, NULL
  ),
  (
    '${failedEquipmentId}', :'organization_id', 'LAY-FAILED-05',
    'Вітрина з помилкою summary', 'Layout Lab C · Zone Epsilon', 'Layout Lab C', 'Zone Epsilon',
    NULL, NULL, 'Холодильна вітрина', 'NEXOLAB', 'Catalog Failed', 'CAT-FAILED-05',
    '3M2', DATE '2026-01-14', DATE '2026-07-24', 'active', 'offline', 0, 0, 0,
    0, 1, 0, NULL, 1, 'equipment-layouts-acceptance', CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP, NULL, NULL
  )
ON CONFLICT (organization_id, code) DO NOTHING;

INSERT INTO equipment_images (
  id,
  organization_id,
  equipment_id,
  storage_key,
  original_filename,
  media_type,
  size_bytes,
  width_px,
  height_px,
  checksum_sha256,
  object_etag,
  created_by,
  created_at,
  retired_by,
  retired_at
)
VALUES
  (
    '${currentImageId}', :'organization_id', '${currentEquipmentId}', '${currentStorageKey}',
    'layout-current.png', 'image/png', :image_size, 1200, 800, :'image_checksum', NULL,
    'equipment-layouts-acceptance', CURRENT_TIMESTAMP, NULL, NULL
  ),
  (
    '${changedImageId}', :'organization_id', '${changedEquipmentId}', '${changedStorageKey}',
    'layout-changed.png', 'image/png', :image_size, 1200, 800, :'image_checksum', NULL,
    'equipment-layouts-acceptance', CURRENT_TIMESTAMP, NULL, NULL
  ),
  (
    '${draftOnlyImageId}', :'organization_id', '${draftOnlyEquipmentId}', '${draftOnlyStorageKey}',
    'layout-draft-only.png', 'image/png', :image_size, 1200, 800, :'image_checksum', NULL,
    'equipment-layouts-acceptance', CURRENT_TIMESTAMP, NULL, NULL
  )
ON CONFLICT (id) DO NOTHING;

INSERT INTO refrigeration_layout_drafts (
  id,
  organization_id,
  equipment_id,
  version,
  image_id,
  placements,
  created_at,
  updated_at
)
VALUES
  (
    '52000000-0000-4000-8000-000000000001', :'organization_id', '${currentEquipmentId}', 1,
    '${currentImageId}',
    '[{"sensor_id":"sensor-current-a","x":0.25,"y":0.4},{"sensor_id":"sensor-current-b","x":0.75,"y":0.65}]'::json,
    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
  ),
  (
    '52000000-0000-4000-8000-000000000002', :'organization_id', '${changedEquipmentId}', 2,
    '${changedImageId}',
    '[{"sensor_id":"sensor-changed-a","x":0.62,"y":0.58}]'::json,
    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
  ),
  (
    '52000000-0000-4000-8000-000000000003', :'organization_id', '${draftOnlyEquipmentId}', 1,
    '${draftOnlyImageId}',
    '[{"sensor_id":"sensor-draft-a","x":0.45,"y":0.5}]'::json,
    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
  ),
  (
    '52000000-0000-4000-8000-000000000004', :'organization_id', '${noImageEquipmentId}', 1,
    NULL,
    '[{"sensor_id":"sensor-no-image-a","x":0.5,"y":0.5}]'::json,
    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
  ),
  (
    '52000000-0000-4000-8000-000000000005', :'organization_id', '${failedEquipmentId}', 1,
    NULL, '[]'::json, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
  )
ON CONFLICT (organization_id, equipment_id) DO UPDATE SET
  version = EXCLUDED.version,
  image_id = EXCLUDED.image_id,
  placements = EXCLUDED.placements,
  updated_at = CURRENT_TIMESTAMP;

INSERT INTO refrigeration_layout_revisions (
  id,
  organization_id,
  equipment_id,
  revision,
  source_draft_version,
  image_id,
  placements,
  published_by,
  published_at
)
VALUES
  (
    '53000000-0000-4000-8000-000000000001', :'organization_id', '${currentEquipmentId}', 1, 1,
    '${currentImageId}',
    '[{"sensor_id":"sensor-current-a","x":0.25,"y":0.4},{"sensor_id":"sensor-current-b","x":0.75,"y":0.65}]'::json,
    'layout-acceptance-publisher', CURRENT_TIMESTAMP - INTERVAL '30 minutes'
  ),
  (
    '53000000-0000-4000-8000-000000000002', :'organization_id', '${changedEquipmentId}', 1, 1,
    '${changedImageId}',
    '[{"sensor_id":"sensor-changed-a","x":0.3,"y":0.3}]'::json,
    'layout-acceptance-publisher', CURRENT_TIMESTAMP - INTERVAL '20 minutes'
  )
ON CONFLICT (organization_id, equipment_id, revision) DO NOTHING;
`;

  composeExec(
    "postgres",
    [
      "psql",
      "-U",
      postgresUser,
      "-d",
      postgresDatabase,
      "-v",
      "ON_ERROR_STOP=1",
      "-v",
      `organization_id=${organizationId}`,
      "-v",
      `image_size=${fixturePng.byteLength}`,
      "-v",
      `image_checksum=${checksum}`,
    ],
    sql,
  );
}

function writeDatabaseEvidence(): void {
  const output = composeExec("postgres", [
    "psql",
    "-U",
    postgresUser,
    "-d",
    postgresDatabase,
    "-P",
    "pager=off",
    "-c",
    [
      "SELECT e.code, e.lifecycle_status, d.version AS draft_version,",
      "       d.image_id, json_array_length(d.placements) AS draft_placements,",
      "       r.revision, r.source_draft_version,",
      "       json_array_length(r.placements) AS published_placements",
      "FROM refrigeration_equipment e",
      "JOIN refrigeration_layout_drafts d",
      "  ON d.organization_id = e.organization_id AND d.equipment_id = e.id",
      "LEFT JOIN refrigeration_layout_revisions r",
      "  ON r.organization_id = e.organization_id AND r.equipment_id = e.id",
      `WHERE e.organization_id = '${organizationId}' AND e.code LIKE 'LAY-%'`,
      "ORDER BY e.code, r.revision;",
    ].join(" "),
  ]);
  writeFileSync(path.join(evidenceDirectory, "equipment-layouts-database-state.txt"), output);
}

test("renders and navigates the authenticated Equipment Layouts catalog", async ({ browser }) => {
  seedEquipmentLayoutFixtures();
  const context = await authenticatedContext(browser);
  const page = await context.newPage();
  const requests = observeEquipmentRequests(page);
  const signedImageResponses = observeSignedImageResponses(page);
  let injectedFailureCount = 0;

  await page.route(`**/api/v1/equipment/${failedEquipmentId}/layout/published`, async (route) => {
    if (route.request().method() !== "GET") {
      await route.continue();
      return;
    }
    injectedFailureCount += 1;
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        detail: {
          code: "equipment_layouts_acceptance_partial_failure",
          message: "Injected partial layout summary failure",
        },
      }),
    });
  });

  try {
    await test.step("render real lifecycle fixtures while preserving one partial failure", async () => {
      await page.goto("/equipment-layouts", { waitUntil: "domcontentloaded" });
      await expect(page.getByText("Viewer Acceptance", { exact: true })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Схеми обладнання" })).toBeVisible();
      await expect(page.getByText("Показано 5 із 5", { exact: true })).toBeVisible();

      await expect(cardFor(page, "LAY-CURRENT-01")).toContainText("Опублікована · актуальна");
      await expect(cardFor(page, "LAY-CHANGED-02")).toContainText("Є нові зміни");
      await expect(cardFor(page, "LAY-DRAFT-03")).toContainText("Лише чернетка");
      await expect(cardFor(page, "LAY-NOIMAGE-04")).toContainText("Немає фото");
      await expect(cardFor(page, "LAY-NOIMAGE-04")).toContainText("Виведене");
      await expect(cardFor(page, "LAY-FAILED-05")).toContainText("Помилка summary");
      await expect(cardFor(page, "LAY-FAILED-05").getByText("Повторити завантаження")).toBeVisible();
      expect(injectedFailureCount).toBeGreaterThan(0);

      await expect.poll(() => requests.length).toBeGreaterThanOrEqual(11);
      expect(requests.every((request) => request.authorization)).toBe(true);
      expect(requests.every((request) => request.organization === organizationId)).toBe(true);
      expect(requests.every((request) => request.method === "GET")).toBe(true);

      await page.screenshot({
        path: path.join(evidenceDirectory, "equipment-layouts-catalog.png"),
        fullPage: true,
      });
    });

    await test.step("persist combined filters through the URL and reload", async () => {
      const search = page.getByPlaceholder("Код, назва, модель або розташування");
      await search.fill("LAY-CURRENT-01");
      await page.getByLabel("Лабораторія").selectOption({ label: "Layout Lab A" });
      await page.getByLabel("Стан схеми").selectOption("published-current");

      await expect(page.getByText("Показано 1 із 5", { exact: true })).toBeVisible();
      await expect(cardFor(page, "LAY-CURRENT-01")).toBeVisible();
      await expect(cardFor(page, "LAY-CHANGED-02")).toHaveCount(0);
      await expect
        .poll(() => {
          const url = new URL(page.url());
          return {
            q: url.searchParams.get("q"),
            lab: url.searchParams.get("lab"),
            layout: url.searchParams.get("layout"),
          };
        })
        .toEqual({
          q: "LAY-CURRENT-01",
          lab: "Layout Lab A",
          layout: "published-current",
        });

      await page.reload({ waitUntil: "domcontentloaded" });
      await expect(search).toHaveValue("LAY-CURRENT-01");
      await expect(page.getByLabel("Лабораторія")).toHaveValue("Layout Lab A");
      await expect(page.getByLabel("Стан схеми")).toHaveValue("published-current");
      await expect(page.getByText("Показано 1 із 5", { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Очистити" }).click();
      await expect(page.getByText("Показано 5 із 5", { exact: true })).toBeVisible();
    });

    await test.step("render a signed read-only image with normalized sensor markers", async () => {
      await page.getByRole("button", { name: "Переглянути опубліковану схему LAY-CURRENT-01" }).click();
      const dialog = page.getByRole("dialog", { name: /LAY-CURRENT-01/ });
      await expect(dialog).toBeVisible();
      await expect(dialog.getByText("Опублікована схема · r1", { exact: true })).toBeVisible();
      await expect(dialog.locator("img")).toBeVisible();
      await expect(dialog.locator('[title="sensor-current-a"]')).toHaveAttribute(
        "style",
        /left: 25%;.*top: 40%;/,
      );
      await expect(dialog.locator('[title="sensor-current-b"]')).toHaveAttribute(
        "style",
        /left: 75%;.*top: 65%;/,
      );
      await expect.poll(() => signedImageResponses.some((response) => response.status === 200)).toBe(true);
      const signedResponse = signedImageResponses.find((response) => response.status === 200);
      expect(signedResponse).toBeDefined();
      expect(signedResponse?.queryKeys.some((key) => key.toLowerCase() === "x-amz-signature")).toBe(true);

      await page.screenshot({
        path: path.join(evidenceDirectory, "equipment-layouts-published-preview.png"),
        fullPage: true,
      });
      await page.getByRole("button", { name: "Закрити попередній перегляд" }).click();
      await expect(dialog).toBeHidden();
    });

    await test.step("navigate to the canonical refrigeration detail workflow", async () => {
      const link = cardFor(page, "LAY-CURRENT-01").getByRole("link", {
        name: "Відкрити картку обладнання LAY-CURRENT-01",
      });
      await expect(link).toHaveAttribute("href", `/refrigeration/${currentEquipmentId}`);
      await link.click();
      await expect(page).toHaveURL(new RegExp(`/refrigeration/${currentEquipmentId}$`));
    });

    writeDatabaseEvidence();
    writeFileSync(
      path.join(evidenceDirectory, "equipment-layouts-summary.json"),
      `${JSON.stringify(
        {
          organizationId,
          fixtures: {
            publishedCurrent: "LAY-CURRENT-01",
            publishedWithDraft: "LAY-CHANGED-02",
            draftOnly: "LAY-DRAFT-03",
            noImage: "LAY-NOIMAGE-04",
            partialFailure: "LAY-FAILED-05",
          },
          injectedFailureCount,
          equipmentRequests: requests,
          signedImageResponses,
          canonicalDetailPath: `/refrigeration/${currentEquipmentId}`,
          mutationsObserved: requests.filter((request) => request.method !== "GET").length,
        },
        null,
        2,
      )}\n`,
    );
  } finally {
    await context.close();
  }
});

function cardFor(page: Page, code: string) {
  return page.locator("article").filter({ hasText: code });
}

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for Equipment Layouts acceptance`);
  return value;
}
