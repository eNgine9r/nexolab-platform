import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  CommissioningConnection,
  CommissioningConnectionInventory,
  CommissioningRepository,
} from "@/features/equipment/commissioning-repository";
import { compareAdapterInventories, Rs485AdapterFinder } from "./rs485-adapter-finder";

const connection = (
  id: string,
  overrides: Partial<CommissioningConnection> = {},
): CommissioningConnection => ({
  busId: `commissioning-${id}`,
  stableTransportIdentifier: `/dev/serial/by-id/usb-${id}`,
  ownership: "available_commissioning",
  present: true,
  availableForPreflight: true,
  serial: null,
  ...overrides,
});
const inventory = (...connections: CommissioningConnection[]): CommissioningConnectionInventory => ({
  schemaVersion: 1,
  nodeId: "edge",
  connections,
});

describe("RS-485 adapter identification", () => {
  it("identifies only one new present and available commissioning adapter", () => {
    const existing = connection("old", { ownership: "production_bus", busId: "rs485-main" });
    const candidate = connection("new");
    expect(compareAdapterInventories(inventory(existing), inventory(existing, candidate))).toEqual({
      kind: "found",
      connection: candidate,
    });
    expect(compareAdapterInventories(inventory(existing), inventory(existing))).toEqual({ kind: "none" });
    expect(
      compareAdapterInventories(inventory(existing), inventory(existing, candidate, connection("new2"))),
    ).toEqual({ kind: "ambiguous" });
    expect(compareAdapterInventories(inventory(existing), inventory(candidate))).toEqual({ kind: "changed" });
    expect(
      compareAdapterInventories(
        inventory(existing),
        inventory(existing, connection("new", { availableForPreflight: false })),
      ),
    ).toEqual({ kind: "unavailable" });
    expect(
      compareAdapterInventories(
        inventory(existing),
        inventory(existing, connection("new", { ownership: "production_bus" })),
      ),
    ).toEqual({ kind: "unavailable" });
  });

  it("rejects duplicate identities, changed nodes and previously disconnected adapters", () => {
    const old = connection("old");
    const next = connection("new");
    expect(compareAdapterInventories(inventory(old), inventory(old, { ...next, busId: old.busId }))).toEqual({
      kind: "changed",
    });
    expect(
      compareAdapterInventories(
        inventory(old),
        inventory(old, { ...next, stableTransportIdentifier: old.stableTransportIdentifier }),
      ),
    ).toEqual({ kind: "changed" });
    expect(compareAdapterInventories(inventory(old), { ...inventory(old, next), nodeId: "other" })).toEqual({
      kind: "changed",
    });
    expect(compareAdapterInventories(inventory(old), inventory({ ...old, present: false }, next))).toEqual({
      kind: "changed",
    });
  });

  it("fetches two snapshots and requires explicit selection", async () => {
    const newAdapter = connection("new");
    const listConnections = vi
      .fn()
      .mockResolvedValueOnce(inventory())
      .mockResolvedValueOnce(inventory(newAdapter));
    const onSelect = vi.fn();
    const onInventoryChanged = vi.fn();
    render(
      <Rs485AdapterFinder
        repository={{ listConnections } as unknown as CommissioningRepository}
        disabled={false}
        onInventoryChanged={onInventoryChanged}
        onSelect={onSelect}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Знайти новий адаптер" }));
    fireEvent.click(await screen.findByRole("button", { name: "Я підключив адаптер" }));
    fireEvent.click(await screen.findByRole("button", { name: "Вибрати цей адаптер" }));
    expect(onSelect).toHaveBeenCalledOnce();
    expect(onSelect).toHaveBeenCalledWith(newAdapter.busId);
    expect(onInventoryChanged).toHaveBeenCalledTimes(2);
    expect(listConnections).toHaveBeenCalledTimes(2);
  });

  it("fails closed on inventory errors and requires a new baseline", async () => {
    const listConnections = vi
      .fn()
      .mockResolvedValueOnce(inventory())
      .mockRejectedValueOnce(new Error("offline"));
    render(
      <Rs485AdapterFinder
        repository={{ listConnections } as unknown as CommissioningRepository}
        disabled={false}
        onInventoryChanged={vi.fn()}
        onSelect={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Знайти новий адаптер" }));
    fireEvent.click(await screen.findByRole("button", { name: "Я підключив адаптер" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Не вдалося отримати список адаптерів");
    expect(screen.queryByRole("button", { name: "Вибрати цей адаптер" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Знайти новий адаптер" })).toBeEnabled();
  });

  it("discards a late response after the repository changes", async () => {
    let resolveOld!: (value: CommissioningConnectionInventory) => void;
    const oldRepository = {
      listConnections: vi.fn(
        () =>
          new Promise<CommissioningConnectionInventory>((resolve) => {
            resolveOld = resolve;
          }),
      ),
    } as unknown as CommissioningRepository;
    const newRepository = {
      listConnections: vi.fn().mockResolvedValue(inventory()),
    } as unknown as CommissioningRepository;
    const changed = vi.fn();
    const { rerender } = render(
      <Rs485AdapterFinder
        repository={oldRepository}
        disabled={false}
        onInventoryChanged={changed}
        onSelect={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Знайти новий адаптер" }));
    rerender(
      <Rs485AdapterFinder
        repository={newRepository}
        disabled={false}
        onInventoryChanged={changed}
        onSelect={vi.fn()}
      />,
    );
    resolveOld(inventory(connection("stale")));
    await waitFor(() => expect(screen.getByRole("button", { name: "Знайти новий адаптер" })).toBeEnabled());
    expect(changed).not.toHaveBeenCalled();
  });
});
