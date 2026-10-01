import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  InstrumentationRegistryRepositoryError,
  type InstrumentationRegistryRepository,
  type InstrumentRegistryRecord,
  type SignalRegistryRecord,
} from "@/features/instrumentation/instrumentation-repository";

import { InstrumentationRegistryWorkspace } from "./instrumentation-registry-workspace";

const instrument: InstrumentRegistryRecord = {
  id: "instrument-1",
  inventoryKey: "PT-001",
  displayName: "Suction pressure transmitter",
  instrumentKind: "pressure_transmitter",
  manufacturer: "Emerson",
  model: "PT5N-30M",
  serialNumber: "SN-001",
  pressureReference: "gauge",
  lifecycleState: "active",
  metadata: { source: "canonical" },
  version: 1,
  createdBy: "operator",
  updatedBy: "operator",
  createdAt: "2026-09-18T10:00:00Z",
  updatedAt: "2026-09-18T10:00:00Z",
};

const signal: SignalRegistryRecord = {
  id: "signal-1",
  instrumentId: instrument.id,
  businessKey: "pressure",
  displayName: "Suction pressure",
  physicalQuantity: "pressure",
  engineeringUnit: "bar",
  lifecycleState: "active",
  metadata: { channel: "canonical" },
  version: 1,
  createdBy: "operator",
  updatedBy: "operator",
  createdAt: "2026-09-18T10:00:00Z",
  updatedAt: "2026-09-18T10:00:00Z",
};

function repository(overrides: Partial<InstrumentationRegistryRepository> = {}) {
  const base: InstrumentationRegistryRepository = {
    async listInstruments() {
      return [instrument];
    },
    async getInstrument() {
      return instrument;
    },
    async createInstrument() {
      return instrument;
    },
    async updateInstrument(_id, input) {
      return {
        ...instrument,
        ...input,
        manufacturer: input.manufacturer,
        model: input.model,
        serialNumber: input.serialNumber,
        pressureReference: input.pressureReference,
        metadata: input.metadata ?? {},
        version: instrument.version + 1,
      };
    },
    async listSignals() {
      return [signal];
    },
    async createSignal() {
      return signal;
    },
    async updateSignal(_instrumentId, _signalId, input) {
      return {
        ...signal,
        ...input,
        metadata: input.metadata ?? {},
        version: signal.version + 1,
      };
    },
    async listAcceptanceHistory() {
      return [
        {
          id: "acceptance-1",
          instrumentId: instrument.id,
          acceptedForCalculation: true,
          stateLabel: "lab-approved",
          effectiveFrom: "2026-09-18T10:05:00Z",
          effectiveTo: null,
          revision: 1,
          recordedBy: "operator",
          recordedAt: "2026-09-18T10:05:00Z",
        },
      ];
    },
    async appendAcceptance(_instrumentId, input) {
      return {
        id: "acceptance-2",
        instrumentId: instrument.id,
        acceptedForCalculation: input.acceptedForCalculation,
        stateLabel: input.stateLabel,
        effectiveFrom: input.effectiveFrom.toISOString(),
        effectiveTo: null,
        revision: 2,
        recordedBy: "operator",
        recordedAt: input.effectiveFrom.toISOString(),
      };
    },
  };
  return { ...base, ...overrides } as InstrumentationRegistryRepository;
}

describe("InstrumentationRegistryWorkspace", () => {
  it("never renders demo registry data without a live repository", () => {
    render(<InstrumentationRegistryWorkspace repository={null} canManage />);

    expect(screen.getByText("Instrumentation Registry недоступний")).toBeInTheDocument();
    expect(screen.queryByText(instrument.displayName)).not.toBeInTheDocument();
  });

  it("allows viewer inspection while hiding every mutation control", async () => {
    render(<InstrumentationRegistryWorkspace repository={repository()} canManage={false} />);

    expect(await screen.findAllByText(instrument.displayName)).not.toHaveLength(0);
    expect(await screen.findAllByText("Suction pressure")).not.toHaveLength(0);
    expect(screen.getByText(/r1 · accepted/)).toBeInTheDocument();
    expect(screen.getByText(/Accepted for calculation ≠ calibrated ≠ hardware verified/)).toBeInTheDocument();

    expect(screen.queryByRole("button", { name: /Новий прилад/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Створити Signal/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Додати acceptance record/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Зберегти Instrument/ })).not.toBeInTheDocument();
  });

  it("creates an Instrument without silently appending calculation acceptance", async () => {
    const created: InstrumentRegistryRecord = {
      ...instrument,
      id: "instrument-new",
      inventoryKey: "PT-NEW",
      displayName: "New pressure transmitter",
    };
    const listInstruments = vi
      .fn<InstrumentationRegistryRepository["listInstruments"]>()
      .mockResolvedValueOnce([])
      .mockResolvedValue([created]);
    const createInstrument = vi
      .fn<InstrumentationRegistryRepository["createInstrument"]>()
      .mockResolvedValue(created);
    const appendAcceptance = vi.fn<InstrumentationRegistryRepository["appendAcceptance"]>(
      repository().appendAcceptance,
    );

    render(
      <InstrumentationRegistryWorkspace
        repository={repository({
          listInstruments,
          createInstrument,
          appendAcceptance,
          listSignals: vi.fn(async () => []),
          listAcceptanceHistory: vi.fn(async () => []),
        })}
        canManage
      />,
    );

    expect(await screen.findByText("Canonical Instruments не знайдено.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Новий прилад/ }));
    fireEvent.change(screen.getByLabelText("create instrument inventory key"), {
      target: { value: "PT-NEW" },
    });
    fireEvent.change(screen.getByLabelText("create instrument display name"), {
      target: { value: "New pressure transmitter" },
    });
    fireEvent.change(screen.getByLabelText("create instrument kind"), {
      target: { value: "pressure_transmitter" },
    });
    fireEvent.change(screen.getByLabelText("create instrument pressure reference"), {
      target: { value: "gauge" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Створити" }));

    await waitFor(() => expect(createInstrument).toHaveBeenCalledOnce());
    expect(appendAcceptance).not.toHaveBeenCalled();
    expect(createInstrument.mock.calls[0]?.[0]).toEqual(
      expect.objectContaining({
        inventoryKey: "PT-NEW",
        displayName: "New pressure transmitter",
        pressureReference: "gauge",
        metadata: {},
      }),
    );
    expect(await screen.findByText(/Calculation acceptance ще не надано/)).toBeInTheDocument();
  });

  it("creates a process-neutral Signal and appends explicit acceptance separately", async () => {
    const createSignal = vi.fn<InstrumentationRegistryRepository["createSignal"]>().mockResolvedValue(signal);
    const appendAcceptance = vi.fn<InstrumentationRegistryRepository["appendAcceptance"]>(
      repository().appendAcceptance,
    );
    const repo = repository({ createSignal, appendAcceptance });

    render(<InstrumentationRegistryWorkspace repository={repo} canManage />);

    expect(await screen.findAllByText(instrument.displayName)).not.toHaveLength(0);
    const signalFormHeading = screen.getByText("Новий Signal");
    const signalForm = signalFormHeading.closest("form");
    if (!signalForm) throw new Error("Signal form missing");

    fireEvent.change(within(signalForm).getByLabelText("create signal business key"), {
      target: { value: "suction-pressure-source" },
    });
    fireEvent.change(within(signalForm).getByLabelText("create signal display name"), {
      target: { value: "Suction pressure" },
    });
    fireEvent.change(within(signalForm).getByLabelText("Новий сигнал: фізична величина"), {
      target: { value: "pressure" },
    });
    fireEvent.change(within(signalForm).getByLabelText("Новий сигнал: одиниця вимірювання"), {
      target: { value: "bar" },
    });
    await waitFor(() =>
      expect(within(signalForm).getByRole("button", { name: "Створити Signal" })).toBeEnabled(),
    );
    fireEvent.click(within(signalForm).getByRole("button", { name: "Створити Signal" }));

    await waitFor(() => expect(createSignal).toHaveBeenCalledOnce());
    expect(createSignal.mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({
        physicalQuantity: "pressure",
        engineeringUnit: "bar",
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: /Додати acceptance record/ }));
    await waitFor(() => expect(appendAcceptance).toHaveBeenCalledOnce());
    expect(appendAcceptance.mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({
        acceptedForCalculation: true,
        effectiveFrom: expect.any(Date),
      }),
    );
  });

  it("preserves unseen canonical metadata on complete replacement updates", async () => {
    const updateInstrument = vi.fn<InstrumentationRegistryRepository["updateInstrument"]>(
      repository().updateInstrument,
    );
    const updateSignal = vi.fn<InstrumentationRegistryRepository["updateSignal"]>(repository().updateSignal);

    render(
      <InstrumentationRegistryWorkspace
        repository={repository({ updateInstrument, updateSignal })}
        canManage
      />,
    );

    expect(await screen.findAllByText(instrument.displayName)).not.toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Зберегти Instrument" }));
    await waitFor(() => expect(updateInstrument).toHaveBeenCalledOnce());
    expect(updateInstrument.mock.calls[0]?.[1].metadata).toEqual({ source: "canonical" });

    fireEvent.click(screen.getByRole("button", { name: "Зберегти Signal" }));
    await waitFor(() => expect(updateSignal).toHaveBeenCalledOnce());
    expect(updateSignal.mock.calls[0]?.[2].metadata).toEqual({ channel: "canonical" });
  });

  it("surfaces optimistic-concurrency rejection instead of hiding it", async () => {
    const updateInstrument = vi
      .fn<InstrumentationRegistryRepository["updateInstrument"]>()
      .mockRejectedValue(
        new InstrumentationRegistryRepositoryError(
          "instrument version conflict",
          "instrument_version_conflict",
          409,
          1,
          2,
        ),
      );

    render(<InstrumentationRegistryWorkspace repository={repository({ updateInstrument })} canManage />);

    expect(await screen.findAllByText(instrument.displayName)).not.toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Зберегти Instrument" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("instrument_version_conflict");
    expect(screen.getByRole("alert")).toHaveTextContent("Canonical version: 2");
  });

  it("suggests a collision-free key and requires the operator to choose the pressure unit", async () => {
    const createSignal = vi.fn<InstrumentationRegistryRepository["createSignal"]>().mockResolvedValue(signal);
    render(<InstrumentationRegistryWorkspace repository={repository({ createSignal })} canManage />);
    await screen.findAllByText("Suction pressure");
    const form = screen.getByText("Новий Signal").closest("form")!;
    fireEvent.change(within(form).getByLabelText("create signal display name"), {
      target: { value: "Новий датчик тиску" },
    });
    fireEvent.change(within(form).getByLabelText("Новий сигнал: фізична величина"), {
      target: { value: "pressure" },
    });
    await waitFor(() =>
      expect(within(form).getByLabelText("create signal business key")).toHaveValue("pressure.2"),
    );
    expect(within(form).getByLabelText("Новий сигнал: одиниця вимірювання")).toHaveValue("");
    expect(within(form).getByRole("button", { name: "Створити Signal" })).toBeDisabled();
    expect(createSignal).not.toHaveBeenCalled();
    fireEvent.change(within(form).getByLabelText("Новий сигнал: одиниця вимірювання"), {
      target: { value: "kPa" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Створити Signal" }));
    await waitFor(() => expect(createSignal).toHaveBeenCalledOnce());
    expect(createSignal.mock.calls[0]?.[1]).toEqual({
      businessKey: "pressure.2",
      displayName: "Новий датчик тиску",
      physicalQuantity: "pressure",
      engineeringUnit: "kPa",
      lifecycleState: "active",
      metadata: {},
    });
  });

  it("keeps an intentional business key when the operator changes the quantity", async () => {
    const createSignal = vi.fn<InstrumentationRegistryRepository["createSignal"]>().mockResolvedValue(signal);
    render(<InstrumentationRegistryWorkspace repository={repository({ createSignal })} canManage />);
    await screen.findAllByText("Suction pressure");
    const form = screen.getByText("Новий Signal").closest("form")!;
    fireEvent.change(within(form).getByLabelText("create signal business key"), {
      target: { value: "lab.explicit-key" },
    });
    fireEvent.change(within(form).getByLabelText("Новий сигнал: фізична величина"), {
      target: { value: "pressure" },
    });
    fireEvent.change(within(form).getByLabelText("Новий сигнал: одиниця вимірювання"), {
      target: { value: "bar" },
    });
    fireEvent.change(within(form).getByLabelText("Новий сигнал: фізична величина"), {
      target: { value: "temperature" },
    });
    expect(within(form).getByLabelText("Новий сигнал: одиниця вимірювання")).toHaveValue("degC");
    expect(within(form).getByLabelText("create signal business key")).toHaveValue("lab.explicit-key");
    expect(createSignal).not.toHaveBeenCalled();
  });

  it.each([
    { physicalQuantity: "custom_quantity", engineeringUnit: "custom_unit" },
    { physicalQuantity: "pressure", engineeringUnit: "psi" },
  ])("preserves existing values outside the catalog: %s", async (values) => {
    const existing = { ...signal, ...values };
    const updateSignal = vi
      .fn<InstrumentationRegistryRepository["updateSignal"]>()
      .mockResolvedValue(existing);
    render(
      <InstrumentationRegistryWorkspace
        repository={repository({ listSignals: async () => [existing], updateSignal })}
        canManage
      />,
    );
    await screen.findByLabelText("Редагування сигналу: ключ величини");
    expect(screen.getByLabelText("Редагування сигналу: фізична величина")).toHaveValue("__custom__");
    expect(screen.getByLabelText("Редагування сигналу: ключ величини")).toHaveValue(values.physicalQuantity);
    expect(screen.getByLabelText("Редагування сигналу: одиниця вимірювання")).toHaveValue(
      values.engineeringUnit,
    );
    expect(updateSignal).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Зберегти Signal" }));
    await waitFor(() => expect(updateSignal).toHaveBeenCalledOnce());
    expect(updateSignal.mock.calls[0]).toEqual([
      instrument.id,
      signal.id,
      {
        businessKey: signal.businessKey,
        displayName: signal.displayName,
        ...values,
        lifecycleState: signal.lifecycleState,
        metadata: signal.metadata,
      },
      signal.version,
    ]);
  });

  it("waits for complete organization signal inventory before proposing or creating a key", async () => {
    let resolveSignals: (signals: SignalRegistryRecord[]) => void = () => undefined;
    const pendingSignals = new Promise<SignalRegistryRecord[]>((resolve) => {
      resolveSignals = resolve;
    });
    const createSignal = vi.fn<InstrumentationRegistryRepository["createSignal"]>().mockResolvedValue(signal);
    render(
      <InstrumentationRegistryWorkspace
        repository={repository({ listSignals: () => pendingSignals, createSignal })}
        canManage
      />,
    );
    await screen.findAllByText(instrument.displayName);
    const form = screen.getByText("Новий Signal").closest("form")!;
    fireEvent.change(within(form).getByLabelText("create signal display name"), {
      target: { value: "Новий тиск" },
    });
    fireEvent.change(within(form).getByLabelText("Новий сигнал: фізична величина"), {
      target: { value: "pressure" },
    });
    fireEvent.change(within(form).getByLabelText("Новий сигнал: одиниця вимірювання"), {
      target: { value: "bar" },
    });
    expect(within(form).getByLabelText("create signal business key")).toHaveValue("");
    expect(within(form).getByRole("button", { name: "Створити Signal" })).toBeDisabled();
    expect(createSignal).not.toHaveBeenCalled();
    await act(async () => resolveSignals([signal]));
    expect(within(form).getByLabelText("create signal business key")).toHaveValue("pressure.2");
    expect(within(form).getByRole("button", { name: "Створити Signal" })).toBeEnabled();
  });
  it("checks keys owned by another instrument and waits for that inventory", async () => {
    const other = { ...instrument, id: "instrument-2", displayName: "Другий прилад" };
    let resolveOther: (signals: SignalRegistryRecord[]) => void = () => undefined;
    const pendingOther = new Promise<SignalRegistryRecord[]>((resolve) => {
      resolveOther = resolve;
    });
    const createSignal = vi.fn<InstrumentationRegistryRepository["createSignal"]>().mockResolvedValue(signal);
    const listSignals = vi.fn<InstrumentationRegistryRepository["listSignals"]>((id) =>
      id === other.id ? pendingOther : Promise.resolve([]),
    );
    render(
      <InstrumentationRegistryWorkspace
        repository={repository({
          listInstruments: async () => [instrument, other],
          listSignals,
          createSignal,
        })}
        canManage
      />,
    );
    await screen.findAllByText(instrument.displayName);
    const form = screen.getByText("Новий Signal").closest("form")!;
    fireEvent.change(within(form).getByLabelText("create signal display name"), {
      target: { value: "Новий тиск" },
    });
    fireEvent.change(within(form).getByLabelText("Новий сигнал: фізична величина"), {
      target: { value: "pressure" },
    });
    fireEvent.change(within(form).getByLabelText("Новий сигнал: одиниця вимірювання"), {
      target: { value: "bar" },
    });
    await waitFor(() => expect(listSignals).toHaveBeenCalledWith(other.id, expect.any(AbortSignal)));
    expect(within(form).getByLabelText("create signal business key")).toHaveValue("");
    expect(within(form).getByRole("button", { name: "Створити Signal" })).toBeDisabled();
    expect(createSignal).not.toHaveBeenCalled();
    await act(async () => resolveOther([{ ...signal, instrumentId: other.id }]));
    await waitFor(() =>
      expect(within(form).getByLabelText("create signal business key")).toHaveValue("pressure.2"),
    );
    fireEvent.click(within(form).getByRole("button", { name: "Створити Signal" }));
    await waitFor(() => expect(createSignal).toHaveBeenCalledOnce());
    expect(createSignal.mock.calls[0]?.[1].businessKey).toBe("pressure.2");
  });
});
