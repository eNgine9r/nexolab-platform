import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/script", () => ({ default: () => null }));

import { TelegramMiniAppReport } from "./telegram-miniapp-report";

const INIT_DATA = "query_id=test&auth_date=1788393600&user=%7B%22id%22%3A123%7D&hash=abc";

function snapshotResponse() {
  return {
    report: {
      id: "22222222-2222-2222-2222-222222222222",
      local_report_date: "2026-09-03",
      scheduled_for: "2026-09-03T04:50:00+00:00",
      window_start: "2026-09-02T16:50:00+00:00",
      window_end: "2026-09-03T04:50:00+00:00",
      timezone: "Europe/Kyiv",
      status: "attention",
      payload: {
        schema: "refrigeration-daily-report/v1",
        identity: {
          equipment_name: "Cool jet",
          equipment_code: "CJ-01",
          manufacturer: "NEXOLAB Test",
          model: "Showcase",
        },
        report: {
          local_report_date: "2026-09-03",
          timezone: "Europe/Kyiv",
          scheduled_for: "2026-09-03T04:50:00+00:00",
          window_start: "2026-09-02T16:50:00+00:00",
          window_end: "2026-09-03T04:50:00+00:00",
          analysis_window_minutes: 720,
          status: "attention",
        },
        m_packets: {
          status: "available",
          minimum_c: -18.4,
          maximum_c: -14.2,
          valid_channels: 2,
          configured_channels: 3,
          channels: [
            { channel_id: "m1", label: "M1", status: "available", value_c: -18.4 },
            { channel_id: "m2", label: "M2", status: "available", value_c: -14.2 },
            { channel_id: "m3", label: "M3", status: "unavailable", reason: "stale" },
          ],
        },
        refrigeration_circuit: {
          evaporation_saturation_temperature: { status: "unavailable", reason: "not_implemented" },
          superheat: { status: "unavailable", reason: "not_implemented" },
          condensation_saturation_temperature: { status: "unavailable", reason: "not_implemented" },
          subcooling: { status: "unavailable", reason: "not_implemented" },
        },
        compressor: { status: "available", duty_percent: 43.2, coverage_percent: 98.5 },
        energy: { status: "unavailable", reason: "boundary_evidence_missing" },
        defrost: { status: "available", duration_seconds: 1800 },
        alerts: { active_count: 1, recent_count: 2, items: [] },
        quality: { status: "incomplete", reasons: ["m_packet_coverage_incomplete"] },
      },
    },
  };
}

describe("TelegramMiniAppReport", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/telegram-miniapp?tgWebAppStartParam=report_22222222-2222-2222-2222-222222222222");
    window.Telegram = {
      WebApp: {
        initData: INIT_DATA,
        ready: vi.fn(),
        expand: vi.fn(),
      },
    };
  });

  afterEach(() => {
    vi.restoreAllMocks();
    delete window.Telegram;
    window.history.replaceState({}, "", "/");
  });

  it("renders only persisted report KPIs and clearly labels the view as not live", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(Response.json(snapshotResponse()));

    render(<TelegramMiniAppReport />);

    expect(await screen.findByText("Cool jet")).toBeInTheDocument();
    expect(screen.getByText(/Збережений звіт · не live/)).toBeInTheDocument();
    expect(screen.getByText("-18.4 °C")).toBeInTheDocument();
    expect(screen.getByText("-14.2 °C")).toBeInTheDocument();
    expect(screen.getByText("2/3")).toBeInTheDocument();
    expect(screen.getByText("43.2 %")).toBeInTheDocument();
    expect(screen.getByText("30 хв")).toBeInTheDocument();
    expect(screen.getAllByText("Недоступно").length).toBeGreaterThan(0);
    expect(screen.getByText(/Холодоагент: Недоступно/)).toBeInTheDocument();
    expect(screen.queryByText(/Налаштування/i)).not.toBeInTheDocument();

    const request = fetchMock.mock.calls[0];
    expect(request[0]).toBe("/api/telegram-miniapp/report");
    const body = JSON.parse(String((request[1] as RequestInit).body));
    expect(body).toEqual({
      init_data: INIT_DATA,
      start_hint: "report_22222222-2222-2222-2222-222222222222",
    });
    expect(body).not.toHaveProperty("organization_id");
    expect(body).not.toHaveProperty("identity_id");
  });

  it("fails closed when Telegram did not provide signed initData", async () => {
    window.Telegram = { WebApp: { initData: "" } };
    const fetchMock = vi.spyOn(globalThis, "fetch");

    render(<TelegramMiniAppReport />);

    expect(await screen.findByText(/Telegram не передав підтверджені дані авторизації/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects a malformed snapshot contract instead of rendering fabricated values", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(Response.json({ report: { payload: {} } }));

    render(<TelegramMiniAppReport />);

    await waitFor(() => {
      expect(screen.getByText(/некоректний формат збереженого звіту/)).toBeInTheDocument();
    });
    expect(screen.queryByText("0 kWh")).not.toBeInTheDocument();
  });
});
