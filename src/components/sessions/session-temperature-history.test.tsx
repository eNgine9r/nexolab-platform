import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TelemetrySample } from "@/lib/telemetry/types";

import { SessionTemperatureHistory } from "./session-temperature-history";

vi.mock("@/components/charts/chart-renderer-host", () => ({
  ChartRendererHost: () => <div data-testid="mock-chart-renderer" />,
}));

vi.mock("@/features/charts/echarts-adapter", () => ({
  EChartsRendererAdapter: class {
    resetZoom() {}
  },
}));

function sample(channel: string, minute: number, overrides: Partial<TelemetrySample> = {}): TelemetrySample {
  return {
    event_id: `${channel}-${minute}`,
    node_id: "edge-01",
    equipment_id: "K105",
    channel_id: channel,
    metric: "temperature.probe",
    value: 3 + minute / 100,
    unit: "degC",
    quality: "valid",
    source: "xjp60d",
    alarm: null,
    raw_value: null,
    raw_status: null,
    captured_at: new Date(Date.parse("2026-11-21T10:00:00Z") + minute * 60_000).toISOString(),
    ...overrides,
  };
}

describe("SessionTemperatureHistory (chart audit 2026-11-21)", () => {
  it("plots the session's real channels on a time axis instead of fixed legend entries", () => {
    const samples = [
      ...Array.from({ length: 5 }, (_, minute) => sample("105-01", minute)),
      ...Array.from({ length: 5 }, (_, minute) => sample("105-02", minute)),
    ];
    render(<SessionTemperatureHistory samples={samples} now={Date.parse("2026-11-21T12:00:00Z")} />);

    expect(screen.getByTestId("session-temperature-history")).toBeInTheDocument();
    expect(screen.getAllByText(/105-01/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/105-02/).length).toBeGreaterThan(0);
    expect(screen.queryByText("106-03")).toBeNull(); // the old hard-coded legend is gone
    expect(screen.getAllByText("Застаріло").length).toBeGreaterThan(0); // finished session is not "live"
  });

  it("says plainly when the session has no persisted temperature samples", () => {
    render(<SessionTemperatureHistory samples={[]} />);
    expect(screen.getByTestId("session-temperature-history-empty")).toHaveTextContent(
      "Для цієї сесії ще немає збережених вимірювань температури.",
    );
  });
});
