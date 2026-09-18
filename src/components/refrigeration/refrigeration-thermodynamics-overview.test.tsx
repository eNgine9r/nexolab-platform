import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  CircuitThermodynamicsSnapshot,
  RefrigerationCircuitSummary,
  RefrigerationThermodynamicsRepository,
} from "@/features/refrigeration/thermodynamics-repository";

import { RefrigerationThermodynamicsOverview } from "./refrigeration-thermodynamics-overview";

const observedAt = "2026-09-18T10:00:00.000Z";

function circuit(id: string, name: string): RefrigerationCircuitSummary {
  return { id, equipmentId: "showcase-a", businessKey: id.toUpperCase(), displayName: name };
}

function snapshot(item: RefrigerationCircuitSummary): CircuitThermodynamicsSnapshot {
  return {
    circuit: item,
    observationAt: observedAt,
    metrics: [
      {
        metric: "refrigeration.temperature.evaporation_saturation",
        availability: "available",
        value: -8.4,
        unit: "degC",
        reasonCodes: [],
        observationAt: observedAt,
        effectiveAt: observedAt,
        computedAt: observedAt,
      },
      {
        metric: "refrigeration.temperature.condensation_saturation",
        availability: "available",
        value: 39.2,
        unit: "degC",
        reasonCodes: [],
        observationAt: observedAt,
        effectiveAt: observedAt,
        computedAt: observedAt,
      },
      {
        metric: "refrigeration.superheat",
        availability: "unavailable",
        value: null,
        unit: "K",
        reasonCodes: ["raw_sample_unavailable"],
        observationAt: observedAt,
        effectiveAt: null,
        computedAt: observedAt,
      },
      {
        metric: "refrigeration.subcooling",
        availability: "available",
        value: 4.7,
        unit: "K",
        reasonCodes: [],
        observationAt: observedAt,
        effectiveAt: observedAt,
        computedAt: observedAt,
      },
    ],
  };
}

function repository(items: RefrigerationCircuitSummary[]): RefrigerationThermodynamicsRepository {
  return {
    listForEquipment: vi.fn(async () => items),
    readDerived: vi.fn(async (item) => snapshot(item)),
  };
}
describe("RefrigerationThermodynamicsOverview", () => {
  it("shows a truthful empty state when the equipment has no circuit", async () => {
    render(<RefrigerationThermodynamicsOverview equipmentId="showcase-a" repository={repository([])} />);

    expect(await screen.findByText("Холодильний контур ще не налаштовано")).toBeInTheDocument();
    expect(screen.queryByText("0.0 degC")).not.toBeInTheDocument();
  });

  it("renders every equipment circuit and keeps unavailable metrics explicit", async () => {
    const first = circuit("circuit-a", "Контур A");
    const second = circuit("circuit-b", "Контур B");
    render(
      <RefrigerationThermodynamicsOverview
        equipmentId="showcase-a"
        repository={repository([first, second])}
      />,
    );

    expect(await screen.findByText("Контур A")).toBeInTheDocument();
    expect(screen.getByText("Контур B")).toBeInTheDocument();
    expect(screen.getAllByText("-8.4 degC")).toHaveLength(2);
    expect(screen.getAllByText("39.2 degC")).toHaveLength(2);
    expect(screen.getAllByText("4.7 K")).toHaveLength(2);
    expect(screen.getAllByText("Недоступно")).toHaveLength(2);
    expect(screen.getAllByText("raw_sample_unavailable")).toHaveLength(2);
    expect(screen.queryByText("0.0 K")).not.toBeInTheDocument();
  });
  it("shows API failures and can recover through the bounded manual refresh", async () => {
    const item = circuit("circuit-a", "Контур A");
    const listForEquipment = vi
      .fn<RefrigerationThermodynamicsRepository["listForEquipment"]>()
      .mockRejectedValueOnce(new Error("API недоступний"))
      .mockResolvedValueOnce([item]);
    const repo: RefrigerationThermodynamicsRepository = {
      listForEquipment,
      readDerived: vi.fn(async () => snapshot(item)),
    };

    render(<RefrigerationThermodynamicsOverview equipmentId="showcase-a" repository={repo} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("API недоступний");
    fireEvent.click(screen.getByRole("button", { name: "Оновити термодинаміку" }));
    expect(await screen.findByText("Контур A")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(listForEquipment).toHaveBeenCalledTimes(2);
  });

  it("does not render a demo fallback when no live repository exists", () => {
    render(<RefrigerationThermodynamicsOverview equipmentId="showcase-a" repository={null} />);
    expect(screen.queryByTestId("refrigeration-thermodynamics-overview")).not.toBeInTheDocument();
  });
});
