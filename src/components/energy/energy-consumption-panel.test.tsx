import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EnergyConsumptionPanel } from "./energy-consumption-panel";
import type { EnergyConsumptionLoader } from "@/features/energy/use-energy-consumption";
import type { TelemetrySample } from "@/lib/telemetry/types";

const cumulative: TelemetrySample = {
  event_id: "energy-200",
  node_id: "edge-01",
  captured_at: new Date().toISOString(),
  metric: "electrical.energy.active",
  value: 100.5,
  unit: "kWh",
  quality: "valid",
  source: "modbus",
  equipment_id: "LE01MP-200",
  channel_id: "200-energy-active",
  alarm: null,
  raw_value: 10050,
  raw_status: null,
};

describe("EnergyConsumptionPanel", () => {
  it("shows derived consumption and lets the operator select an independent preset", async () => {
    const load = vi.fn().mockResolvedValue({
      status: "ready",
      valueKwh: 2.5,
      startSample: cumulative,
      endSample: cumulative,
      message: null,
    });
    const loader: EnergyConsumptionLoader = { enabled: true, load };

    render(<EnergyConsumptionPanel unitId={200} currentCumulative={cumulative} loader={loader} />);

    expect(await screen.findByText("2,50 kWh")).toBeInTheDocument();
    expect(screen.getByText("Споживання")).toBeInTheDocument();
    expect(screen.queryByText(/Накопичена енергія/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("24 год"));
    fireEvent.click(screen.getByRole("button", { name: "Сьогодні" }));

    await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
    expect(screen.getByText("Сьогодні")).toBeInTheDocument();
    expect(screen.getByText("Період: з 00:00 до зараз")).toBeInTheDocument();
  });

  it("validates a custom range before applying it", async () => {
    const load = vi.fn().mockResolvedValue({
      status: "ready",
      valueKwh: 1,
      startSample: cumulative,
      endSample: cumulative,
      message: null,
    });
    const loader: EnergyConsumptionLoader = { enabled: true, load };

    render(<EnergyConsumptionPanel unitId={200} currentCumulative={cumulative} loader={loader} />);
    await screen.findByText("1,00 kWh");

    fireEvent.click(screen.getByText("24 год"));
    fireEvent.click(screen.getByRole("button", { name: "Власний період…" }));

    const from = screen.getByLabelText("Від");
    const to = screen.getByLabelText("До");
    fireEvent.change(from, { target: { value: "2026-08-17T20:00" } });
    fireEvent.change(to, { target: { value: "2026-08-17T08:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Застосувати" }));

    expect(
      screen.getByText("Вкажіть коректний початок і кінець: початок має бути раніше завершення."),
    ).toBeInTheDocument();
    expect(load).toHaveBeenCalledTimes(1);
  });
});
