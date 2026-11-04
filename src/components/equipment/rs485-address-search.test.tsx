import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type {
  AddressSearchResult,
  CommissioningRepository,
} from "@/features/equipment/commissioning-repository";
import { Rs485AddressSearch } from "./rs485-address-search";

const connection = {
  nodeId: "edge-01",
  busId: "commissioning-1234567890abcdef",
  stableTransportIdentifier: "/dev/serial/by-id/usb-test",
};
const empty: AddressSearchResult = {
  state: "completed",
  candidates: [],
  exceptionAddresses: [],
  errorCode: null,
};

describe("RS-485 address search", () => {
  it("retries a corrupt reply, continues scanning and reports incomplete evidence separately", async () => {
    const searchAddress = vi
      .fn()
      .mockImplementation(async ({ unitId }) =>
        unitId === 1
          ? { ...empty, state: "failed", errorCode: "malformed_response" }
          : { ...empty, candidates: unitId === 2 ? [2] : [] },
      );
    render(
      <Rs485AddressSearch
        repository={{ searchAddress } as unknown as CommissioningRepository}
        connection={connection}
        disabled={false}
        onSelect={vi.fn()}
        onRunningChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Знайти прилади" }));
    await screen.findByText(/Пошук завершено з помилками/);
    expect(searchAddress).toHaveBeenCalledTimes(248);
    expect(screen.getByRole("alert")).toHaveTextContent("повторної перевірки: 1");
    expect(screen.getByRole("button", { name: "Вибрати адресу 2" })).toBeEnabled();
  });

  it("counts unique responding addresses across profiles and includes unrecognized exception replies", async () => {
    const searchAddress = vi.fn().mockImplementation(async ({ unitId }) => ({
      ...empty,
      candidates: unitId === 3 ? [3] : [],
      exceptionAddresses: unitId === 5 ? [5] : [],
    }));
    render(
      <Rs485AddressSearch
        repository={{ searchAddress } as unknown as CommissioningRepository}
        connection={connection}
        disabled={false}
        onSelect={vi.fn()}
        onRunningChange={vi.fn()}
        profiles={[
          { id: "dixell-xjp60d", version: "dixell-xjp60d-fc03-v1", displayName: "Dixell XJP60D" },
          { id: "f-and-f-le01mp", version: "f-and-f-le01mp-fc03-v2", displayName: "F&F LE-01MP" },
        ]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Знайти прилади" }));
    await screen.findByText(/Пошук завершено/);
    expect(searchAddress).toHaveBeenCalledTimes(494);
    expect(screen.getByRole("status")).toHaveTextContent("Знайдено адрес із приладами: 2");
    expect(screen.getByText(/модель не визначена/)).toBeInTheDocument();
    expect(screen.getByText(/Точну модель ще не підтверджено/)).toHaveTextContent(
      "Dixell XJP60D, F&F LE-01MP",
    );
  });

  it("searches every address and counts all responders without selecting automatically", async () => {
    const searchAddress = vi.fn().mockImplementation(async ({ unitId }) => ({
      ...empty,
      candidates: [3, 7].includes(unitId) ? [unitId] : [],
    }));
    const onSelect = vi.fn();
    render(
      <Rs485AddressSearch
        repository={{ searchAddress } as unknown as CommissioningRepository}
        connection={connection}
        disabled={false}
        onSelect={onSelect}
        onRunningChange={vi.fn()}
      />,
    );
    expect(searchAddress).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Знайти прилади" }));
    await screen.findByText(/Пошук завершено/);
    expect(searchAddress).toHaveBeenCalledTimes(247);
    expect(searchAddress.mock.calls.map(([input]) => input.unitId)).toEqual(
      Array.from({ length: 247 }, (_, i) => i + 1),
    );
    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent("Знайдено адрес із приладами: 2");
    fireEvent.click(screen.getByRole("button", { name: "Вибрати адресу 3" }));
    expect(onSelect).toHaveBeenCalledWith(3, "dixell-xjp60d");
  });

  it("stops future reads and ignores an in-flight late response after cancellation", async () => {
    let resolve!: (value: AddressSearchResult) => void;
    const searchAddress = vi
      .fn()
      .mockResolvedValueOnce({ ...empty, candidates: [1] })
      .mockImplementationOnce(
        () =>
          new Promise<AddressSearchResult>((done) => {
            resolve = done;
          }),
      );
    render(
      <Rs485AddressSearch
        repository={{ searchAddress } as unknown as CommissioningRepository}
        connection={connection}
        disabled={false}
        onSelect={vi.fn()}
        onRunningChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Знайти прилади" }));
    await waitFor(() => expect(searchAddress).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole("button", { name: "Зупинити пошук" }));
    await act(async () => resolve({ ...empty, candidates: [2] }));
    expect(await screen.findByText(/Пошук зупинено/)).toBeInTheDocument();
    expect(searchAddress).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("button", { name: "Вибрати адресу 2" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Вибрати адресу 1" })).toBeEnabled();
  });

  it("aborts and clears old evidence when the adapter context changes", async () => {
    let resolve!: (value: AddressSearchResult) => void;
    const searchAddress = vi.fn().mockImplementation(
      () =>
        new Promise<AddressSearchResult>((done) => {
          resolve = done;
        }),
    );
    const repository = { searchAddress } as unknown as CommissioningRepository;
    const props = { repository, disabled: false, onSelect: vi.fn(), onRunningChange: vi.fn() };
    const { rerender } = render(<Rs485AddressSearch {...props} connection={connection} />);
    fireEvent.click(screen.getByRole("button", { name: "Знайти прилади" }));
    const signal = searchAddress.mock.calls[0][1] as AbortSignal;
    rerender(
      <Rs485AddressSearch
        {...props}
        connection={{ ...connection, busId: "commissioning-0000000000000000" }}
      />,
    );
    expect(signal.aborted).toBe(true);
    await act(async () => resolve({ ...empty, candidates: [1] }));
    expect(screen.queryByRole("button", { name: "Вибрати адресу 1" })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Знайдено адрес із приладами: 0");
  });
});
