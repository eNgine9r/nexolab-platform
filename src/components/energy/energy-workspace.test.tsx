import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EnergyWorkspace } from "./energy-workspace";
import { ENERGY_METERS } from "@/features/energy/energy-telemetry";
import type { EnergyConsumptionLoader } from "@/features/energy/use-energy-consumption";
import type { EnergyTelemetryModel } from "@/hooks/use-energy-telemetry";

vi.mock("@/components/charts/chart-renderer-host", () => ({
  ChartRendererHost: ({ scene }: { scene: { series: import("@/features/charts/domain").ChartSeries[] } }) => (
    <div data-testid="visible-energy-series">
      {scene.series
        .filter((series) => series.visible)
        .map((series) => series.identity.equipmentId)
        .join(",")}
    </div>
  ),
}));

function setup(overrides: Partial<EnergyTelemetryModel> = {}) {
  const telemetry: EnergyTelemetryModel = {
    mode: "live",
    status: "live",
    samples: [],
    freshSamples: [],
    lastCapturedAt: null,
    ageMs: null,
    cadenceAuthority: null,
    selectedMetric: "electrical.voltage",
    setSelectedMetric: vi.fn(),
    historyRange: "7d",
    setHistoryRange: vi.fn(),
    historyWindow: null,
    historySamples: [],
    historyStatus: "ready",
    historyError: null,
    retryHistory: vi.fn(),
    error: null,
    retry: vi.fn(),
    ...overrides,
  };
  const consumption: EnergyConsumptionLoader = { enabled: false, load: vi.fn() };
  render(<EnergyWorkspace telemetry={telemetry} consumption={consumption} />);
  return { telemetry, consumption };
}

function toggle(label: string, selected = true) {
  return screen.getByRole("button", {
    name: `${selected ? "Виключити" : "Додати"} лічильник ${label} з порівняння`,
  });
}

describe("EnergyWorkspace comparison selection", () => {
  it("explains why the final meter cannot be removed and permits adding another", () => {
    setup();
    for (const meter of ENERGY_METERS) expect(toggle(meter.label)).toHaveAttribute("aria-pressed", "true");
    for (const meter of ENERGY_METERS.slice(0, -1)) fireEvent.click(toggle(meter.label));
    const last = ENERGY_METERS.at(-1)!;
    const finalToggle = toggle(last.label);
    expect(finalToggle).toBeDisabled();
    expect(finalToggle).toHaveAccessibleDescription(/Для порівняння потрібен хоча б один лічильник/);
    expect(screen.getByText(/Додайте інший, щоб виключити цей/)).toBeVisible();
    fireEvent.click(finalToggle);
    expect(finalToggle).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(toggle(ENERGY_METERS[0].label, false));
    expect(finalToggle).toBeEnabled();
    expect(screen.queryByText(/Додайте інший, щоб виключити цей/)).not.toBeInTheDocument();
    fireEvent.click(finalToggle);
    expect(toggle(ENERGY_METERS[0].label)).toBeDisabled();
  });

  it("selects only a previously unselected meter without changing range, metric or loaders", () => {
    const { telemetry, consumption } = setup();
    const [first, second] = ENERGY_METERS;
    fireEvent.click(screen.getByRole("button", { name: `Показати лише лічильник ${first.label}` }));
    expect(toggle(first.label)).toBeDisabled();
    expect(toggle(second.label, false)).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: `Показати лише лічильник ${second.label}` }));
    expect(toggle(second.label)).toBeDisabled();
    expect(toggle(first.label, false)).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText(/1 вибрано/)).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Показник" })).toHaveValue("electrical.voltage");
    expect(screen.getByRole("button", { name: "7 діб" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getAllByText("Споживання", { exact: true })).toHaveLength(ENERGY_METERS.length);
    expect(telemetry.setSelectedMetric).not.toHaveBeenCalled();
    expect(telemetry.setHistoryRange).not.toHaveBeenCalled();
    expect(telemetry.retry).not.toHaveBeenCalled();
    expect(consumption.load).not.toHaveBeenCalled();
  });
});

it("Only this clears stale Solo and Hide overrides, including a repeat selection", async () => {
  const samples = [ENERGY_METERS[0], ENERGY_METERS.at(-1)!].map((meter) => ({
    event_id: `voltage-${meter.unitId}`,
    node_id: "edge-01",
    equipment_id: meter.equipmentId,
    channel_id: `${meter.unitId}-voltage`,
    captured_at: new Date().toISOString(),
    metric: "electrical.voltage",
    value: 230,
    unit: "V",
    quality: "valid" as const,
    source: "modbus",
    alarm: null,
    raw_value: 230,
    raw_status: null,
  }));
  setup({ historySamples: samples });
  await waitFor(() => expect(screen.getAllByRole("button", { name: "Hide" })).toHaveLength(2));
  fireEvent.click(screen.getAllByRole("button", { name: "Solo" })[0]);
  fireEvent.click(screen.getByRole("button", { name: "Показати лише лічильник SDM120M" }));
  await waitFor(() => expect(screen.getByTestId("visible-energy-series")).toHaveTextContent("SDM120M-1"));
  expect(screen.getByRole("button", { name: "Hide" })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByRole("button", { name: "Hide" }));
  expect(screen.getByTestId("visible-energy-series")).toBeEmptyDOMElement();
  fireEvent.click(screen.getByRole("button", { name: "Показати лише лічильник SDM120M" }));
  await waitFor(() => expect(screen.getByTestId("visible-energy-series")).toHaveTextContent("SDM120M-1"));
});
