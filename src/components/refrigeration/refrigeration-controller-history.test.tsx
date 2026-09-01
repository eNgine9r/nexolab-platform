import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RefrigerationControllerHistory } from "@/components/refrigeration/refrigeration-controller-history";
import { EMBRACO_METRICS } from "@/features/refrigeration/controller-monitoring";
import type { RefrigerationControllerModel } from "@/features/refrigeration/use-refrigeration-controller";
import type { TelemetrySample } from "@/lib/telemetry/types";

vi.mock("@/components/refrigeration/refrigeration-controller-chart", () => ({
  RefrigerationControllerChart: (props: {
    title: string;
    scene: { xDomain: { fromMs: number; toMs: number } };
    onViewportDomainChange?: (domain: { fromMs: number; toMs: number }) => void;
  }) => (
    <button
      type="button"
      data-testid={`mock-chart-${props.title}`}
      onClick={() =>
        props.onViewportDomainChange?.({
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

function speedSample(second: number, value: number): TelemetrySample {
  return {
    event_id: `speed-${second}`,
    node_id: "node-1",
    captured_at: new Date(range.from.getTime() + second * 1000).toISOString(),
    metric: EMBRACO_METRICS.compressorSpeed,
    value,
    unit: "rpm",
    quality: "valid",
    source: "modbus",
    equipment_id: "embraco-2",
    channel_id: "compressor-speed",
    alarm: null,
    raw_value: value,
    raw_status: null,
  };
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
      [EMBRACO_METRICS.compressorSpeed, [speedSample(0, 4500), speedSample(60, 0), speedSample(120, 0)]],
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
describe("RefrigerationControllerHistory compressor analysis range", () => {
  it("recalculates duty from the compressor-chart selection and resets to the loaded range", async () => {
    render(<RefrigerationControllerHistory controller={controllerModel()} />);

    expect(dutyCard()).toHaveTextContent("50.0 %");
    expect(screen.getByTestId("compressor-analysis-range")).toHaveTextContent("Повний період");

    fireEvent.click(screen.getByTestId("mock-chart-Швидкість компресора"));

    await waitFor(() => expect(dutyCard()).toHaveTextContent("100.0 %"));
    expect(screen.getByTestId("compressor-analysis-range")).toHaveTextContent("Вибраний відрізок графіка");

    fireEvent.click(screen.getByRole("button", { name: "Скинути вибір" }));

    await waitFor(() => expect(dutyCard()).toHaveTextContent("50.0 %"));
    expect(screen.getByTestId("compressor-analysis-range")).toHaveTextContent("Повний період");
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
