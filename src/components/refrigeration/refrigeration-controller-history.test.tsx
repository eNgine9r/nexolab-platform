import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RefrigerationControllerHistory } from "@/components/refrigeration/refrigeration-controller-history";
import { triggerBrowserBlobDownload } from "@/features/live-dashboards/browser-download";
import { EMBRACO_METRICS } from "@/features/refrigeration/controller-monitoring";
import type { ChartXDomain } from "@/features/charts/domain";
import type { RefrigerationControllerModel } from "@/features/refrigeration/use-refrigeration-controller";
import type { TelemetrySample } from "@/lib/telemetry/types";

vi.mock("@/features/live-dashboards/browser-download", () => ({
  triggerBrowserBlobDownload: vi.fn(),
}));

vi.mock("@/components/refrigeration/refrigeration-controller-chart", () => ({
  RefrigerationControllerChart: (props: {
    title: string;
    scene: { xDomain: { fromMs: number; toMs: number } };
    sharedCursorMs: number | null;
    onSharedCursorChange: (timestampMs: number | null) => void;
    onRangeSelectionChange?: (domain: { fromMs: number; toMs: number }) => void;
    rangeSelection: ChartXDomain | null;
    viewportDomain: ChartXDomain;
    onViewportChange: (domain: ChartXDomain | null) => void;
    afterPlot?: React.ReactNode;
  }) => (
    <div
      data-testid={`mock-chart-container-${props.title}`}
      data-shared-cursor={props.sharedCursorMs ?? ""}
      data-chart-x-domain-to-ms={props.viewportDomain.toMs}
      data-selection-to-ms={props.rangeSelection?.toMs ?? ""}
    >
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
      <button
        type="button"
        data-testid={`mock-zoom-${props.title}`}
        onClick={() =>
          props.onViewportChange({
            fromMs: props.scene.xDomain.fromMs,
            toMs: props.scene.xDomain.toMs - 30_000,
          })
        }
      >
        zoom
      </button>
      <button
        type="button"
        data-testid={`mock-cursor-${props.title}`}
        onClick={() => props.onSharedCursorChange(props.scene.xDomain.fromMs + 60_000)}
      >
        cursor
      </button>
      <button
        type="button"
        data-testid={`mock-clear-cursor-${props.title}`}
        onClick={() => props.onSharedCursorChange(null)}
      >
        clear cursor
      </button>
      {props.afterPlot}
    </div>
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
  it("shares one cursor timestamp across both controller charts and clears stale range cursors", async () => {
    const { rerender } = render(<RefrigerationControllerHistory controller={controllerModel()} />);
    const temperature = screen.getByTestId("mock-chart-container-Температури контролера · °C");
    const compressor = screen.getByTestId("mock-chart-container-Швидкість компресора");

    expect(temperature).toHaveAttribute("data-shared-cursor", "");
    expect(compressor).toHaveAttribute("data-shared-cursor", "");

    fireEvent.click(screen.getByTestId("mock-cursor-Температури контролера · °C"));
    const sharedTimestamp = String(range.from.getTime() + 60_000);
    expect(temperature).toHaveAttribute("data-shared-cursor", sharedTimestamp);
    expect(compressor).toHaveAttribute("data-shared-cursor", sharedTimestamp);

    fireEvent.click(screen.getByTestId("mock-clear-cursor-Швидкість компресора"));
    expect(temperature).toHaveAttribute("data-shared-cursor", "");
    expect(compressor).toHaveAttribute("data-shared-cursor", "");

    fireEvent.click(screen.getByTestId("mock-cursor-Швидкість компресора"));
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
      expect(screen.getByTestId("mock-chart-container-Температури контролера · °C")).toHaveAttribute(
        "data-shared-cursor",
        "",
      ),
    );
    expect(screen.getByTestId("mock-chart-container-Швидкість компресора")).toHaveAttribute(
      "data-shared-cursor",
      "",
    );
  });
  it("synchronizes duty, compressor starts and relay traceability with chart selection and reset", async () => {
    render(<RefrigerationControllerHistory controller={controllerModel()} />);

    expect(dutyCard()).toHaveTextContent("50.0 %");
    expect(startsCard()).toHaveTextContent("1");
    expect(screen.getByTestId("compressor-analysis-range")).toHaveTextContent("Повний період");
    expect(screen.getByTestId("compressor-analysis-range")).toHaveTextContent("затисніть ліву кнопку миші");
    expect(screen.getByTestId("relay-analysis-lanes")).toHaveTextContent("Relay 1");
    expect(screen.getByTestId("relay-analysis-lanes")).toHaveTextContent("Relay 4");
    expect(screen.getAllByLabelText("Relay 1 OFF").length).toBeGreaterThan(0);
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

  it("shares temperature selection and zoom with the RPM chart and lanes without conflating selection and viewport", () => {
    const controller = controllerModel();
    const history = new Map(controller.history);
    history.set(EMBRACO_METRICS.controlState, [
      sample(0, EMBRACO_METRICS.controlState, 2, "state", "mode"),
      sample(30, EMBRACO_METRICS.controlState, 3, "state", "mode"),
      sample(60, EMBRACO_METRICS.controlState, 4, "state", "mode"),
      sample(90, EMBRACO_METRICS.controlState, 1, "state", "mode"),
    ]);
    render(<RefrigerationControllerHistory controller={{ ...controller, history }} />);

    const temperature = screen.getByTestId("mock-chart-container-Температури контролера · °C");
    const rpm = screen.getByTestId("mock-chart-container-Швидкість компресора");
    const lanes = screen.getByTestId("relay-analysis-lanes");
    const selectedEnd = String(range.from.getTime() + 60_000);
    const fullEnd = String(range.to.getTime());

    fireEvent.click(screen.getByTestId("mock-chart-Температури контролера · °C"));
    expect(rpm).toHaveAttribute("data-selection-to-ms", selectedEnd);
    expect(lanes).toHaveAttribute("data-chart-x-domain-to-ms", fullEnd);
    expect(screen.getByText("Тривалість відтайки").closest("article")).toHaveTextContent("30 с");

    fireEvent.click(screen.getByTestId("mock-cursor-Швидкість компресора"));
    expect(
      lanes.querySelector('[data-timeline-label="Відтайка"] [data-testid="timeline-cursor-state"]'),
    ).toHaveTextContent("OFF");
    expect(
      lanes.querySelector('[data-timeline-label="Relay 1"] [data-testid="timeline-cursor-state"]'),
    ).toHaveTextContent("OFF");

    fireEvent.click(screen.getByTestId("mock-zoom-Швидкість компресора"));
    expect(temperature).toHaveAttribute("data-chart-x-domain-to-ms", String(range.to.getTime() - 30_000));
    expect(lanes).toHaveAttribute("data-chart-x-domain-to-ms", String(range.to.getTime() - 30_000));
    expect(rpm).toHaveAttribute("data-selection-to-ms", selectedEnd);
    fireEvent.click(screen.getByRole("button", { name: "Наблизити відрізок" }));
    expect(temperature).toHaveAttribute("data-chart-x-domain-to-ms", selectedEnd);
    expect(lanes).toHaveAttribute("data-chart-x-domain-to-ms", selectedEnd);

    fireEvent.click(screen.getByRole("button", { name: "Скинути вибір" }));
    expect(temperature).toHaveAttribute("data-chart-x-domain-to-ms", fullEnd);
    expect(rpm).toHaveAttribute("data-selection-to-ms", "");
    expect(lanes).toHaveAttribute("data-chart-x-domain-to-ms", fullEnd);
  });

  it("exports the currently selected interval through the browser download manager", async () => {
    const download = vi.mocked(triggerBrowserBlobDownload);
    download.mockClear();
    render(<RefrigerationControllerHistory controller={controllerModel()} />);

    fireEvent.click(screen.getByTestId("mock-chart-Швидкість компресора"));
    await waitFor(() => expect(startsCard()).toHaveTextContent("0"));
    fireEvent.click(screen.getByRole("button", { name: "Експорт CSV" }));

    expect(download).toHaveBeenCalledTimes(1);
    const argument = download.mock.calls[0]?.[0];
    expect(argument?.filename).toMatch(/^nexolab-embraco-2-.*\.csv$/);
    expect(argument?.blob.type).toBe("text/csv;charset=utf-8");
    expect(await argument?.blob.text()).toContain("compressor.start_count");
    expect(await argument?.blob.text()).toContain(range.from.toISOString());
    expect(await argument?.blob.text()).not.toContain("relay-bits-120");
  });

  it("fails closed instead of reporting confirmed zero or exporting while history is unavailable", () => {
    const download = vi.mocked(triggerBrowserBlobDownload);
    download.mockClear();
    const { rerender } = render(
      <RefrigerationControllerHistory
        controller={controllerModel({ history: new Map(), historyLoading: true })}
      />,
    );

    expect(dutyCard()).toHaveTextContent("—");
    expect(startsCard()).toHaveTextContent("—");
    const exportButton = screen.getByRole("button", { name: "Експорт CSV" });
    expect(exportButton).toBeDisabled();
    fireEvent.click(exportButton);
    expect(download).not.toHaveBeenCalled();

    rerender(
      <RefrigerationControllerHistory
        controller={controllerModel({ history: new Map(), historyError: "history failed" })}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("history failed");
    expect(dutyCard()).toHaveTextContent("—");
    expect(startsCard()).toHaveTextContent("—");
    expect(screen.getByRole("button", { name: "Експорт CSV" })).toBeDisabled();
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

describe("Embraco probe history and CSV UI", () => {
  it("shows a separate clearly marked raw probe chart with the same history range", () => {
    const model = controllerModel();
    render(<RefrigerationControllerHistory controller={model} />);
    expect(screen.getByTestId("embraco-unverified-scale-note")).toHaveTextContent(
      "попередній коефіцієнт ×0,01",
    );
    expect(screen.getByTestId("mock-chart-container-Діагностика · вихідні raw")).toHaveAttribute(
      "data-chart-x-domain-to-ms",
      String(range.to.getTime()),
    );
    fireEvent.click(screen.getByTestId("mock-cursor-Діагностика · вихідні raw"));
    expect(screen.getByTestId("mock-chart-container-Швидкість компресора")).toHaveAttribute(
      "data-shared-cursor",
      String(range.from.getTime() + 60_000),
    );
  });
});
