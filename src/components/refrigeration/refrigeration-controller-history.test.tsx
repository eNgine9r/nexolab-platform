import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RefrigerationControllerHistory } from "@/components/refrigeration/refrigeration-controller-history";
import { triggerBrowserBlobDownload } from "@/features/live-dashboards/browser-download";
import { EMBRACO_METRICS } from "@/features/refrigeration/controller-monitoring";
import type { RefrigerationControllerModel } from "@/features/refrigeration/use-refrigeration-controller";
import type { TelemetrySample } from "@/lib/telemetry/types";

vi.mock("@/features/live-dashboards/browser-download", () => ({
  triggerBrowserBlobDownload: vi.fn(),
}));

vi.mock("@/components/refrigeration/refrigeration-controller-chart", () => ({
  RefrigerationControllerChart: (props: {
    title: string;
    scene: { xDomain: { fromMs: number; toMs: number } };
    onRangeSelectionChange?: (domain: { fromMs: number; toMs: number }) => void;
    rangeSelectionEnabled?: boolean;
  }) => (
    <button
      type="button"
      data-testid={`mock-chart-${props.title}`}
      onClick={() =>
        props.onRangeSelectionChange?.({
          fromMs: props.scene.xDomain.fromMs,
          toMs: props.scene.xDomain.fromMs + 60_000,
        })
      }
    >
      {props.title}
    </button>
  ),
}));

const range = {
  from: new Date("2026-08-28T00:00:00Z"),
  to: new Date("2026-08-28T00:02:00Z"),
};

function sample(
  second: number,
  metric: string,
  value: number,
  unit: string,
  channelId: string,
): TelemetrySample {
  return {
    event_id: `${channelId}-${second}`,
    node_id: "node-1",
    captured_at: new Date(range.from.getTime() + second * 1000).toISOString(),
    metric,
    value,
    unit,
    quality: "valid",
    source: "modbus",
    equipment_id: "embraco-2",
    channel_id: channelId,
    alarm: null,
    raw_value: value,
    raw_status: null,
  };
}

function speedSample(second: number, value: number): TelemetrySample {
  return sample(second, EMBRACO_METRICS.compressorSpeed, value, "rpm", "compressor-speed");
}

function relaySample(second: number, value: number): TelemetrySample {
  return sample(second, EMBRACO_METRICS.relays, value, "bitfield", "relay-bits");
}

function controllerModel(
  overrides: Partial<RefrigerationControllerModel> = {},
): RefrigerationControllerModel {
  return {
    binding: {
      id: "binding-1",
      equipmentId: "cool-jet",
      nodeId: "node-1",
      controllerFamily: "embraco",
      controllerEquipmentId: "embraco-2",
      unitId: 2,
      profileVersion: "test",
      boundAt: range.from.toISOString(),
      verifiedFromTelemetry: true,
    },
    bindingLoading: false,
    latest: null,
    latestError: null,
    history: new Map([
      [EMBRACO_METRICS.compressorSpeed, [speedSample(0, 4500), speedSample(60, 0), speedSample(120, 4500)]],
      [EMBRACO_METRICS.relays, [relaySample(0, 0), relaySample(60, 0), relaySample(120, 1)]],
    ]),
    historyLoading: false,
    historyError: null,
    preset: "custom",
    range,
    customRange: range,
    setPreset: vi.fn(),
    setCustomRange: vi.fn(),
    ...overrides,
  };
}

function dutyCard(): HTMLElement {
  return screen.getByText("Коефіцієнт роботи").closest("article")!;
}

function startsCard(): HTMLElement {
  return screen.getByText("Пуски компресора").closest("article")!;
}

describe("RefrigerationControllerHistory selected analysis range", () => {
  it("synchronizes duty, compressor starts and relay traceability with chart selection and reset", async () => {
    render(<RefrigerationControllerHistory controller={controllerModel()} />);

    expect(dutyCard()).toHaveTextContent("50.0 %");
    expect(startsCard()).toHaveTextContent("1");
    expect(screen.getByTestId("compressor-analysis-range")).toHaveTextContent("Повний період");
    expect(screen.getByTestId("compressor-analysis-range")).toHaveTextContent("затисніть ліву кнопку миші");
    expect(screen.getByTestId("relay-analysis-lanes")).toHaveTextContent("Relay 1");
    expect(screen.getByTestId("relay-analysis-lanes")).toHaveTextContent("Relay 4");
    expect(screen.getByTestId("relay-transition-journal")).toHaveTextContent("Подій: 1");
    expect(screen.getByTestId("relay-transition-journal")).toHaveTextContent("OFF → ON");

    fireEvent.click(screen.getByTestId("mock-chart-Швидкість компресора"));

    await waitFor(() => expect(dutyCard()).toHaveTextContent("100.0 %"));
    expect(startsCard()).toHaveTextContent("0");
    expect(screen.getByTestId("compressor-analysis-range")).toHaveTextContent("Вибраний відрізок графіка");
    expect(screen.getByTestId("relay-transition-journal")).toHaveTextContent("Подій: 0");

    fireEvent.click(screen.getByRole("button", { name: "Скинути вибір" }));

    await waitFor(() => expect(dutyCard()).toHaveTextContent("50.0 %"));
    expect(startsCard()).toHaveTextContent("1");
    expect(screen.getByTestId("relay-transition-journal")).toHaveTextContent("Подій: 1");
    expect(screen.getByTestId("compressor-analysis-range")).toHaveTextContent("Повний період");
  });

  it("exports the currently selected interval through the browser download manager", async () => {
    const download = vi.mocked(triggerBrowserBlobDownload);
    download.mockClear();
    render(<RefrigerationControllerHistory controller={controllerModel()} />);

    fireEvent.click(screen.getByTestId("mock-chart-Швидкість компресора"));
    await waitFor(() => expect(startsCard()).toHaveTextContent("0"));
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));

    expect(download).toHaveBeenCalledTimes(1);
    const argument = download.mock.calls[0]?.[0];
    expect(argument?.filename).toMatch(/^nexolab-embraco-2-.*\.csv$/);
    expect(argument?.blob.type).toBe("text/csv;charset=utf-8");
    expect(await argument?.blob.text()).toContain("compressor.start_count");
    expect(await argument?.blob.text()).toContain(range.from.toISOString());
    expect(await argument?.blob.text()).not.toContain("relay-bits-120");
  });

  it("clears a stale sub-selection when the loaded history range changes", async () => {
    const { rerender } = render(<RefrigerationControllerHistory controller={controllerModel()} />);
    fireEvent.click(screen.getByTestId("mock-chart-Швидкість компресора"));
    await waitFor(() => expect(dutyCard()).toHaveTextContent("100.0 %"));

    const nextRange = {
      from: new Date("2026-08-28T01:00:00Z"),
      to: new Date("2026-08-28T01:02:00Z"),
    };
    rerender(
      <RefrigerationControllerHistory
        controller={controllerModel({ range: nextRange, customRange: nextRange })}
      />,
    );

    await waitFor(() =>
      expect(screen.getByTestId("compressor-analysis-range")).toHaveTextContent("Повний період"),
    );
    expect(screen.queryByRole("button", { name: "Скинути вибір" })).not.toBeInTheDocument();
  });
});
