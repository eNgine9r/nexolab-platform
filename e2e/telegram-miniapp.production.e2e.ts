import { expect, test } from "@playwright/test";

const INIT_DATA =
  "auth_date=1788382800&start_param=report_22222222-2222-2222-2222-222222222222&hash=synthetic";

const snapshot = {
  id: "22222222-2222-2222-2222-222222222222",
  local_report_date: "2026-09-03",
  scheduled_for: "2026-09-03T04:50:00+00:00",
  window_start: "2026-09-02T16:50:00+00:00",
  window_end: "2026-09-03T04:50:00+00:00",
  timezone: "Europe/Kyiv",
  status: "attention",
  payload: {
    schema: "refrigeration-daily-report/v1",
    identity: { equipment_name: "Cool jet", equipment_code: "CJ-01" },
    report: {
      local_report_date: "2026-09-03",
      timezone: "Europe/Kyiv",
      window_start: "2026-09-02T16:50:00+00:00",
      window_end: "2026-09-03T04:50:00+00:00",
      analysis_window_minutes: 720,
      status: "attention",
    },
    m_packets: {
      minimum_c: -1.2,
      maximum_c: 8.4,
      valid_channels: 2,
      configured_channels: 3,
      channels: [
        { channel_id: "M1", label: "M-пакет 1", status: "available", value_c: -1.2 },
        { channel_id: "M2", label: "M-пакет 2", status: "available", value_c: 8.4 },
        { channel_id: "M3", label: "M-пакет 3", status: "unavailable", reason: "stale" },
      ],
    },
    refrigeration_circuit: {
      evaporation_saturation_temperature: { status: "unavailable", reason: "not_implemented" },
      superheat: { status: "unavailable", reason: "not_implemented" },
      condensation_saturation_temperature: { status: "unavailable", reason: "not_implemented" },
      subcooling: { status: "unavailable", reason: "not_implemented" },
    },
    compressor: { status: "available", duty_percent: 42.5, coverage_percent: 99.1 },
    energy: { status: "available", interval_kwh: 3.21 },
    defrost: { status: "available", duration_seconds: 1080 },
    alerts: { active_count: 1, recent_count: 2, items: [] },
    quality: { status: "incomplete", reasons: ["m_packet_coverage_incomplete"] },
  },
};

test.use({ viewport: { width: 390, height: 844 } });

test("Telegram Mini App renders the persisted report without starting the desktop shell", async ({ page }) => {
  const observedRequests: string[] = [];
  page.on("request", (request) => observedRequests.push(request.url()));
  await page.addInitScript((initData) => {
    Object.defineProperty(window, "Telegram", {
      configurable: true,
      value: { WebApp: { initData, ready() {}, expand() {}, setHeaderColor() {}, setBackgroundColor() {} } },
    });
  }, INIT_DATA);
  await page.route("https://telegram.org/js/**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/javascript", body: "" });
  });
  await page.route("**/api/telegram-miniapp/report", async (route) => {
    const request = route.request();
    expect(request.method()).toBe("POST");
    expect(request.postDataJSON()).toEqual({
      init_data: INIT_DATA,
      start_hint: "report_22222222-2222-2222-2222-222222222222",
    });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "Cache-Control": "no-store" },
      body: JSON.stringify({ report: snapshot }),
    });
  });

  await page.goto("/telegram-miniapp");

  await expect(page.getByRole("heading", { name: "Cool jet" })).toBeVisible();
  await expect(page.getByText("Увага", { exact: true })).toBeVisible();
  await expect(page.getByText("Збережений звіт · не live")).toBeVisible();
  await expect(page.getByText("42.5 %")).toBeVisible();
  await expect(page.getByText("3.21 kWh")).toBeVisible();
  await expect(page.getByText("18 хв")).toBeVisible();
  await expect(page.getByText("evidence валідний")).toBeVisible();
  await expect(page.getByText(/неповне покриття M-пакетів/)).toBeVisible();
  await expect(page.getByText("Налаштування")).toHaveCount(0);

  expect(observedRequests.some((url) => url.includes("/api/auth/"))).toBe(false);
  expect(observedRequests.some((url) => url.includes("/api/v1/telemetry"))).toBe(false);
});
