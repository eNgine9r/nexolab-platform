import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TelemetrySample } from "@/lib/telemetry/types";

import { TemperatureChart } from "./temperature-chart";

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
    source: "dixell-xjp60d",
    equipment_id: `K${channelId.split("-")[0]}`,
    channel_id: channelId,
    alarm: null,
    raw_value: value === null ? null : Math.round(value * 10),
    raw_status: quality === "sensor_error" ? 0x1103 : 0x1100,
  };
}

describe("TemperatureChart live discovery", () => {
  it("renders newly valid KK2 and KK1 channels without a frontend allowlist", () => {
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
    expect(screen.queryByText("101-01")).not.toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "Реальний графік історії температур XJP60D" }),
    ).toBeVisible();
  });
});
