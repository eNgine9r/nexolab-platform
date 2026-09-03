import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/script", () => ({ default: () => null }));

import { TelegramMiniAppReport } from "./telegram-miniapp-report";

const INIT_DATA = "auth_date=1788382800&start_param=report_22222222-2222-2222-2222-222222222222&hash=test";

const snapshot = {
  id: "22222222-2222-2222-2222-222222222222",
  local_report_date: "2026-09-03",
  scheduled_for: "2026-09-03T04:50:00+00:00",
  window_start: "2026-09-02T16:50:00+00:00",
  window_end: "2026-09-03T04:50:00+00:00",
  timezone: "Europe/Kyiv",
  status: "normal",
  payload: {
    schema: "refrigeration-daily-report/v1",
    identity: {
      equipment_name: "Cool jet",
      manufacturer: "NEXOLAB",
      model: "Showcase A",
    },
    report: {
      local_report_date: "2026-09-03",
      timezone: "Europe/Kyiv",
      scheduled_for: "2026-09-03T04:50:00+00:00",
      window_start: "2026-09-02T16:50:00+00:00",
      window_end: "2026-09-03T04:50:00+00:00",
      status: "normal",
    },
    m_packets: {
      minimum_c: -1.2,
      maximum_c: 8.4,
      valid_channels: 2,
      configured_channels: 3,
      channels: [
        {
          channel_id: "M1",
          label: "M-пакет 1",
          status: "available",
          value_c: -1.2,
          captured_at: "2026-09-03T04:49:00+00:00",
        },
        {
          channel_id: "M2",
          label: "M-пакет 2",
          status: "available",
          value_c: 8.4,
          captured_at: "2026-09-03T04:49:00+00:00",
        },
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
    alerts: {
      active_count: 1,
      recent_count: 2,
      items: [
        {
          id: "alert-1",
          severity: "warning",
          channel_id: "M2",
          metric: "temperature.probe",
          triggered_at: "2026-09-03T03:30:00+00:00",
        },
      ],
    },
    quality: { status: "incomplete", reasons: ["m_packet_coverage_incomplete"] },
  },
};

function installTelegram(initData = INIT_DATA) {
  Object.defineProperty(window, "Telegram", {
    configurable: true,
    value: {
      WebApp: {
        initData,
        ready: vi.fn(),
        expand: vi.fn(),
        setHeaderColor: vi.fn(),
        setBackgroundColor: vi.fn(),
      },
    },
  });
}

describe("TelegramMiniAppReport", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    delete window.Telegram;
  });

  afterEach(() => {
    delete window.Telegram;
  });

  it("sends only signed initData plus the opaque start hint and renders persisted report fields", async () => {
    installTelegram();
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(Response.json({ report: snapshot }));

    render(<TelegramMiniAppReport />);

    expect(await screen.findByText("Cool jet")).toBeInTheDocument();
    expect(screen.getByText("Норма")).toBeInTheDocument();
    expect(screen.getByText("Збережений звіт · не live")).toBeInTheDocument();
    expect(screen.getAllByText("-1.2 °C").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("8.4 °C").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("42.5 %")).toBeInTheDocument();
    expect(screen.getByText("3.21 kWh")).toBeInTheDocument();
    expect(screen.getByText("18 хв")).toBeInTheDocument();
    expect(screen.getAllByText("Недоступно").length).toBeGreaterThanOrEqual(4);
    expect(screen.getByText(/неповне покриття M-пакетів/)).toBeInTheDocument();
    expect(screen.queryByText("Налаштування")).not.toBeInTheDocument();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, request] = fetchMock.mock.calls[0];
    const body = JSON.parse(String(request?.body));
    expect(body).toEqual({
      init_data: INIT_DATA,
      start_hint: "report_22222222-2222-2222-2222-222222222222",
    });
    expect(body).not.toHaveProperty("organization_id");
    expect(body).not.toHaveProperty("identity_id");
    expect(body).not.toHaveProperty("user_id");
  });

  it("does not fabricate zero counts and exposes unavailable energy evidence", async () => {
    installTelegram();
    const degraded = structuredClone(snapshot);
    Reflect.deleteProperty(degraded.payload.m_packets, "valid_channels");
    Reflect.deleteProperty(degraded.payload.alerts, "active_count");
    Reflect.deleteProperty(degraded.payload.alerts, "recent_count");
    Object.assign(degraded.payload.energy, { status: "unavailable", reason: "continuity_gap" });
    Reflect.deleteProperty(degraded.payload.energy, "interval_kwh");
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(Response.json({ report: degraded }));

    render(<TelegramMiniAppReport />);

    expect(await screen.findByText("Cool jet")).toBeInTheDocument();
    expect(screen.getByText("coverage недоступне")).toBeInTheDocument();
    expect(screen.getAllByText("— активних").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("розрив безперервності")).toBeInTheDocument();
    expect(screen.queryByText("0 активних")).not.toBeInTheDocument();
  });

  it("fails closed when the server denies the linked Telegram identity", async () => {
    installTelegram();
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      Response.json({ detail: { code: "miniapp_access_denied" } }, { status: 403 }),
    );

    render(<TelegramMiniAppReport />);

    expect(await screen.findByText("Доступ не підтверджено")).toBeInTheDocument();
    expect(screen.queryByText("Cool jet")).not.toBeInTheDocument();
  });

  it("does not contact NEXOLAB when Telegram WebApp context exists without signed initData", async () => {
    installTelegram("");
    const fetchMock = vi.spyOn(globalThis, "fetch");

    render(<TelegramMiniAppReport />);

    expect(await screen.findByText("Відкрийте звіт через Telegram")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).not.toHaveBeenCalled());
  });
});
