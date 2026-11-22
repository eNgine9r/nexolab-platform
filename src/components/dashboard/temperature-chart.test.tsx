import { act, fireEvent, render, screen } from "@testing-library/react";
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

  it("renders current and persisted temperatures from replacement units 1 and 7", async () => {
    const samples = [
      { ...sample("rs485-sdm120:1-S01", 4.5), equipment_id: "XJP60D-S:rs485-sdm120:1" },
      { ...sample("rs485-sdm120:7-S02", 5.5), equipment_id: "XJP60D-S:rs485-sdm120:7" },
    ];
    await act(async () => {
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
    });
    expect(screen.getByText("rs485-sdm120:1-S01")).toBeInTheDocument();
    expect(screen.getByText("rs485-sdm120:7-S02")).toBeInTheDocument();
    expect(screen.getByText("4,5 °C")).toBeInTheDocument();
    expect(screen.getByTestId("overview-chart-panel")).toBeVisible();
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

  it("bounds many live values by default and expands only on operator request", async () => {
    const channels = [
      "101-01",
      "101-02",
      "101-03",
      "101-04",
      "101-05",
      "101-06",
      "102-01",
      "102-02",
      "102-03",
      "102-04",
    ];

    await act(async () => {
      render(
        <TemperatureChart
          mode="live"
          status="live"
          samples={channels.map((channelId, index) =>
            sample(
              channelId,
              channelId === "102-04" ? null : 3 + index / 10,
              channelId === "102-04" ? "sensor_error" : "valid",
            ),
          )}
        />,
      );
      await Promise.resolve();
    });

    expect(screen.getByText("Поточні значення")).toBeInTheDocument();
    expect(screen.getByText("101-01")).toBeInTheDocument();
    expect(screen.getByText("102-04")).toBeInTheDocument();
    expect(screen.getByText("sensor_error")).toBeInTheDocument();
    expect(screen.queryByText("102-02")).not.toBeInTheDocument();
    expect(screen.queryByText("102-03")).not.toBeInTheDocument();

    const expand = screen.getByRole("button", { name: /\+ 2 датчиків · Показати всі/ });
    expect(expand).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(expand);

    expect(screen.getByText("102-02")).toBeInTheDocument();
    expect(screen.getByText("102-03")).toBeInTheDocument();
    expect(screen.getByText("102-04")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Згорнути" })).toHaveAttribute("aria-expanded", "true");
  });
});

describe("TemperatureChart custom history period (#1683)", () => {
  it("offers the unified presets plus a custom period and applies the entered window", async () => {
    const onHistoryCustomRange = vi.fn();
    const samples = [sample("104-03", 4.1)];
    await act(async () => {
      render(
        <TemperatureChart
          mode="live"
          status="live"
          samples={samples}
          historySamples={samples}
          historyStatus="ready"
          onHistoryRangeChange={vi.fn()}
          onHistoryCustomRange={onHistoryCustomRange}
          onHistoryRetry={vi.fn()}
        />,
      );
    });

    for (const label of ["1 година", "6 годин", "24 години", "7 днів", "Власний період"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
    fireEvent.click(screen.getByRole("button", { name: "Власний період" }));
    fireEvent.change(screen.getByLabelText("Від"), { target: { value: "2026-11-10T08:00" } });
    fireEvent.change(screen.getByLabelText("До"), { target: { value: "2026-11-10T09:30" } });
    fireEvent.click(screen.getByRole("button", { name: "Застосувати" }));

    expect(onHistoryCustomRange).toHaveBeenCalledOnce();
    const [fromMs, toMs] = onHistoryCustomRange.mock.calls[0] as [number, number];
    expect(toMs - fromMs).toBe(90 * 60 * 1000);
    expect(screen.queryByTestId("overview-custom-range-form")).not.toBeInTheDocument();
  });

  it("marks a selected custom period as fixed", async () => {
    const samples = [sample("104-03", 4.1)];
    await act(async () => {
      render(
        <TemperatureChart
          mode="live"
          status="live"
          samples={samples}
          historySamples={samples}
          historyRange="custom"
          historyWindow={{ from: "2026-07-31T06:00:00.000Z", to: "2026-07-31T09:00:00.000Z" }}
          historyStatus="ready"
          onHistoryRangeChange={vi.fn()}
          onHistoryCustomRange={vi.fn()}
          onHistoryRetry={vi.fn()}
        />,
      );
    });

    expect(screen.getByRole("button", { name: "Власний період" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("overview-custom-range-notice")).toHaveTextContent(
      "Фіксований період: нові вимірювання не додаються",
    );
  });
});
