import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
    expect(await screen.findByText("Suction pressure")).toBeInTheDocument();
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
    fireEvent.change(within(signalForm).getByLabelText("create signal physical quantity"), {
      target: { value: "pressure" },
    });
    fireEvent.change(within(signalForm).getByLabelText("create signal engineering unit"), {
      target: { value: "bar" },
    });
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
});
