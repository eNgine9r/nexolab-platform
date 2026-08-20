import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TelemetrySample } from "@/lib/telemetry/types";

import { TemperatureChart } from "./temperature-chart";

vi.mock("@/components/dashboard/overview-chart-panel", () => ({
  OverviewChartPanel: () => <div data-testid="overview-chart-panel" />,
}));

function sample(
  channelId: string,
  value: number | null,
  quality: TelemetrySample["quality"] = "valid",
): TelemetrySample {
  return {
    event_id: `event-${channelId}`,
    node_id: "edge-01",
    captured_at: "2026-07-31T08:00:00Z",
    metric: "temperature.probe",
    value,
    unit: "degC",
    quality,
    source: "dashboard-acceptance",
    equipment_id: `K${channelId.split("-")[0]}`,
    channel_id: channelId,
    alarm: null,
    raw_value: value === null ? null : Math.round(value * 10),
    raw_status: quality === "sensor_error" ? 0x1103 : 0x1100,
  };
}

describe("TemperatureChart live discovery", () => {
  it("shows an active channel as initializing before its first sample", () => {
    render(
      <TemperatureChart
        mode="live"
        status="connecting"
        samples={[]}
        targetDiagnostics={[
          {
            target_id: "xjp60d:126-04",
            channel_id: "126-04",
            state: "initializing",
            recovery_state: "initializing",
            last_attempt_at: null,
            last_success_at: null,
            last_error: null,
            consecutive_failures: 0,
            cooldown: false,
            cooldown_remaining_seconds: 0,
            next_due_in_seconds: 0.5,
            outcomes: {
              attempts: 0,
              successes: 0,
              communication_failures: 0,
            },
          },
        ]}
      />,
    );

    expect(screen.getByText("126-04")).toBeInTheDocument();
    expect(screen.getByText("Ініціалізація")).toBeInTheDocument();
    expect(screen.queryByText("Немає активних температурних каналів.")).not.toBeInTheDocument();
  });

  it("describes a hide-all Overview selection without implying acquisition stopped", () => {
    render(
      <TemperatureChart
        mode="live"
        status="live"
        samples={[]}
        historySamples={[]}
        historyStatus="ready"
        allMonitoredChannelsHidden
      />,
    );

    expect(screen.getByText("Усі температурні канали приховані на Огляді.")).toBeInTheDocument();
    expect(screen.getByText(/Безперервний збір даних продовжується/)).toBeInTheDocument();
    expect(screen.queryByText("Немає активних температурних каналів.")).not.toBeInTheDocument();
    expect(screen.queryByText("Немає валідної температурної історії.")).not.toBeInTheDocument();
  });

  it("renders a proven sensor error instead of hiding the channel", () => {
    render(<TemperatureChart mode="live" status="live" samples={[sample("126-01", null, "sensor_error")]} />);

    expect(screen.getByText("126-01")).toBeInTheDocument();
    expect(screen.getByText("sensor_error")).toBeInTheDocument();
  });

  it("renders newly valid KK2 and KK1 channels without a source allowlist", () => {
    const samples = [
      sample("106-03", 4.5),
      sample("110-06", 5.5),
      sample("126-04", 6.5),
      sample("101-01", null, "sensor_error"),
    ];

    render(
      <TemperatureChart
        mode="live"
        status="live"
        samples={samples}
        historySamples={samples}
        historyStatus="ready"
        onHistoryRangeChange={vi.fn()}
        onHistoryRetry={vi.fn()}
      />,
    );

    expect(screen.getByText("106-03")).toBeInTheDocument();
    expect(screen.getByText("110-06")).toBeInTheDocument();
    expect(screen.getByText("126-04")).toBeInTheDocument();
    expect(screen.getByText("4,5 °C")).toBeInTheDocument();
    expect(screen.getByText("6,5 °C")).toBeInTheDocument();
    expect(screen.getByText("101-01")).toBeInTheDocument();
    expect(screen.getByText("sensor_error")).toBeInTheDocument();
    expect(screen.getByTestId("overview-chart-panel")).toBeVisible();
  });
});
