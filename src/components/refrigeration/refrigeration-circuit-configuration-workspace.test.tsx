import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  RefrigerationCircuitConfigurationRepository,
  RefrigerationCircuitRecord,
} from "@/features/refrigeration/circuit-configuration-repository";

import { RefrigerationCircuitConfigurationWorkspace } from "./refrigeration-circuit-configuration-workspace";

const circuit: RefrigerationCircuitRecord = {
  id: "circuit-1",
  equipmentId: "equipment-1",
  businessKey: "main",
  displayName: "Основний контур",
  createdBy: "operator",
  createdAt: "2026-09-18T09:00:00Z",
};

function repository(overrides: Partial<RefrigerationCircuitConfigurationRepository> = {}) {
  const base: RefrigerationCircuitConfigurationRepository = {
    async listCircuits() {
      return [circuit];
    },
    async createCircuit() {
      return circuit;
    },
    async listLifecycle() {
      return [
        {
          id: "lifecycle-1",
          circuitId: circuit.id,
          state: "active" as const,
          calculationEnabled: true,
          validFrom: "2026-09-18T09:00:00Z",
          validTo: null,
          revision: 1,
          recordedBy: "operator",
          recordedAt: "2026-09-18T09:00:00Z",
        },
      ];
    },
    async appendLifecycle(_id, input) {
      return {
        id: "lifecycle-2",
        circuitId: circuit.id,
        state: input.state,
        calculationEnabled: input.state === "active",
        validFrom: input.validFrom.toISOString(),
        validTo: null,
        revision: 2,
        recordedBy: "operator",
        recordedAt: input.validFrom.toISOString(),
      };
    },
    async listConfigurations() {
      return [
        {
          id: "config-1",
          circuitId: circuit.id,
          refrigerantCode: "R290",
          calculationPolicyVersion: "lab-v1",
          propertyProviderProfile: "coolprop-heos/8.0.0",
          validFrom: "2026-09-18T09:00:00Z",
          validTo: null,
          revision: 1,
          recordedBy: "operator",
          recordedAt: "2026-09-18T09:00:00Z",
        },
      ];
    },
    async appendConfiguration(_id, input) {
      return {
        id: "config-2",
        circuitId: circuit.id,
        refrigerantCode: input.refrigerantCode,
        calculationPolicyVersion: input.calculationPolicyVersion,
        propertyProviderProfile: input.propertyProviderProfile,
        validFrom: input.validFrom.toISOString(),
        validTo: null,
        revision: 2,
        recordedBy: "operator",
        recordedAt: input.validFrom.toISOString(),
      };
    },
    async listBindings() {
      return [];
    },
    async appendBinding(_id, input) {
      return {
        id: "binding-1",
        circuitId: circuit.id,
        signalId: input.signalId,
        role: input.role,
        physicalQuantity: "pressure",
        engineeringUnit: "bar",
        instrumentKind: "pressure_transmitter",
        pressureReference: "gauge" as const,
        validFrom: input.validFrom.toISOString(),
        validTo: null,
        revision: 1,
        recordedBy: "operator",
        recordedAt: input.validFrom.toISOString(),
        endedBy: null,
        endedAt: null,
      };
    },
    async endBinding(_id, role, validTo) {
      return {
        id: "binding-1",
        circuitId: circuit.id,
        signalId: "signal-1",
        role,
        physicalQuantity: "pressure",
        engineeringUnit: "bar",
        instrumentKind: "pressure_transmitter",
        pressureReference: "gauge" as const,
        validFrom: "2026-09-18T09:00:00Z",
        validTo: validTo.toISOString(),
        revision: 1,
        recordedBy: "operator",
        recordedAt: "2026-09-18T09:00:00Z",
        endedBy: "operator",
        endedAt: validTo.toISOString(),
      };
    },
    async listPolicies() {
      return [
        {
          id: "policy-1",
          version: "lab-v1",
          maximumAgeMs: 30000,
          maximumFutureClockSkewMs: 1000,
          maximumCrossInputSkewMs: 5000,
          acceptedCalibrationStates: ["valid"],
          requireCalibrationAtObservation: true,
          calibrationRequiredRoles: ["suction_pressure"],
          createdBy: "operator",
          createdAt: "2026-09-18T09:00:00Z",
        },
      ];
    },
    async listBindingCandidates() {
      return [
        {
          signalId: "signal-1",
          instrumentId: "instrument-1",
          signalDisplayName: "Suction pressure",
          instrumentDisplayName: "PT-1",
          physicalQuantity: "pressure",
          engineeringUnit: "bar",
          instrumentKind: "pressure_transmitter",
          pressureReference: "gauge" as const,
        },
      ];
    },
  };
  return { ...base, ...overrides } as RefrigerationCircuitConfigurationRepository;
}

describe("RefrigerationCircuitConfigurationWorkspace", () => {
  it("never renders demo configuration when the live repository is absent", () => {
    render(
      <RefrigerationCircuitConfigurationWorkspace
        equipmentId="equipment-1"
        repository={null}
        canManage
      />,
    );

    expect(screen.getByText("Конфігурація контуру недоступна")).toBeInTheDocument();
    expect(screen.queryByText("Основний контур")).not.toBeInTheDocument();
  });

  it("allows viewer inspection but hides every mutation surface", async () => {
    render(
      <RefrigerationCircuitConfigurationWorkspace
        equipmentId="equipment-1"
        repository={repository()}
        canManage={false}
      />,
    );

    expect(await screen.findByText("Основний контур")).toBeInTheDocument();
    expect(screen.getByText(/Режим перегляду/)).toBeInTheDocument();
    expect(screen.getByText(/r1 · Активний/)).toBeInTheDocument();
    expect(screen.getByText(/r1 · R290 · lab-v1/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Створити контур/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Додати стан/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Обрати сигнал/ })).not.toBeInTheDocument();
  });

  it("shows a truthful zero-circuit state and creates a canonical circuit for an operator", async () => {
    const listCircuits = vi
      .fn<RefrigerationCircuitConfigurationRepository["listCircuits"]>()
      .mockResolvedValueOnce([])
      .mockResolvedValue([circuit]);
    const createCircuit = vi.fn<RefrigerationCircuitConfigurationRepository["createCircuit"]>(async () => circuit);
    const repo = repository({ listCircuits, createCircuit });

    render(
      <RefrigerationCircuitConfigurationWorkspace
        equipmentId="equipment-1"
        repository={repo}
        canManage
      />,
    );

    expect(await screen.findByText("Для цього обладнання контурів ще немає.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Business key"), { target: { value: "main" } });
    fireEvent.change(screen.getByLabelText("Назва"), { target: { value: "Основний контур" } });
    fireEvent.click(screen.getByRole("button", { name: /Створити контур/ }));

    await waitFor(() => expect(createCircuit).toHaveBeenCalledOnce());
    expect(createCircuit.mock.calls[0]?.[0]).toEqual(
      expect.objectContaining({
        equipmentId: "equipment-1",
        businessKey: "main",
        displayName: "Основний контур",
        initialState: "active",
      }),
    );
    expect(await screen.findByText("Основний контур")).toBeInTheDocument();
  });

  it("fails closed when no canonical calculation policy exists", async () => {
    render(
      <RefrigerationCircuitConfigurationWorkspace
        equipmentId="equipment-1"
        repository={repository({ listPolicies: vi.fn(async () => []) })}
        canManage
      />,
    );

    expect(await screen.findByText("Основний контур")).toBeInTheDocument();
    expect(screen.getByText(/Frontend не створює прихованих\/default thresholds/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Додати версію конфігурації" })).toBeDisabled();
  });

  it("uses backend candidate discovery before binding a semantic role", async () => {
    const listBindingCandidates = vi.fn<
      RefrigerationCircuitConfigurationRepository["listBindingCandidates"]
    >(async () => [
      {
        signalId: "signal-1",
        instrumentId: "instrument-1",
        signalDisplayName: "Suction pressure",
        instrumentDisplayName: "PT-1",
        physicalQuantity: "pressure",
        engineeringUnit: "bar",
        instrumentKind: "pressure_transmitter",
        pressureReference: "gauge",
      },
    ]);
    const appendBinding = vi.fn<
      RefrigerationCircuitConfigurationRepository["appendBinding"]
    >(repository().appendBinding);
    const repo = repository({ listBindingCandidates, appendBinding });

    render(
      <RefrigerationCircuitConfigurationWorkspace
        equipmentId="equipment-1"
        repository={repo}
        canManage
      />,
    );

    const roleTitle = await screen.findByText("Тиск кипіння / всмоктування");
    const card = roleTitle.closest("article");
    if (!card) throw new Error("Role card missing");
    fireEvent.click(within(card).getByRole("button", { name: "Обрати сигнал" }));

    expect(await within(card).findByText(/PT-1 · Suction pressure · bar/)).toBeInTheDocument();
    expect(listBindingCandidates).toHaveBeenCalledWith(
      "suction_pressure",
      expect.any(Date),
    );
    fireEvent.click(within(card).getByRole("button", { name: "Прив’язати" }));

    await waitFor(() => expect(appendBinding).toHaveBeenCalledOnce());
    expect(appendBinding.mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({
        role: "suction_pressure",
        signalId: "signal-1",
        validFrom: expect.any(Date),
      }),
    );
  });
});
