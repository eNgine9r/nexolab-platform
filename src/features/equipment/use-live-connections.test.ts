import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  CommissioningConnectionInventory,
  CommissioningRepository,
  CommissioningSessionWrite,
} from "./commissioning-repository";
import { reconcileLiveConnection, useLiveConnections } from "./use-live-connections";

const inventory: CommissioningConnectionInventory = {
  schemaVersion: 1,
  nodeId: "edge-01",
  connections: [
    {
      busId: "usb-1",
      stableTransportIdentifier: "/dev/serial/by-id/usb-1",
      present: true,
      ownership: "available_commissioning",
      availableForPreflight: true,
      serial: null,
    },
  ],
};
const draft = {
  nodeId: inventory.nodeId,
  busId: "usb-1",
  stableTransportIdentifier: "/dev/serial/by-id/usb-1",
  unitId: 7,
  model: "XJP60D",
} as CommissioningSessionWrite;
const repositoryWith = (listConnections: CommissioningRepository["listConnections"]) =>
  ({ listConnections }) as CommissioningRepository;

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("live USB inventory", () => {
  it("retains a connected selection and clears the address on unplug or identity change", () => {
    expect(reconcileLiveConnection(draft, inventory)).toBe(draft);
    for (const changed of [
      { ...inventory, connections: [] },
      { ...inventory, connections: inventory.connections.map((item) => ({ ...item, present: false })) },
      { ...inventory, nodeId: "other-edge" },
      {
        ...inventory,
        connections: inventory.connections.map((item) => ({
          ...item,
          stableTransportIdentifier: "other-usb",
        })),
      },
    ])
      expect(reconcileLiveConnection(draft, changed)).toEqual({
        ...draft,
        nodeId: null,
        busId: null,
        stableTransportIdentifier: null,
        unitId: null,
      });
  });

  it("refreshes every two seconds, pauses hidden tabs and resumes on focus", async () => {
    vi.useFakeTimers();
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    const list = vi.fn().mockResolvedValue(inventory);
    const repository = repositoryWith(list);
    const receive = vi.fn();
    const { unmount } = renderHook(() => useLiveConnections(repository, true, receive, vi.fn()));
    await act(async () => {});
    expect(list).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(list).toHaveBeenCalledTimes(2);
    visibility.mockReturnValue("hidden");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(list).toHaveBeenCalledTimes(2);
    visibility.mockReturnValue("visible");
    await act(async () => window.dispatchEvent(new Event("focus")));
    expect(list).toHaveBeenCalledTimes(3);
    expect(receive).toHaveBeenCalledTimes(3);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not overlap requests and aborts/ignores an old organization response", async () => {
    vi.useFakeTimers();
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    let resolveOld!: (value: CommissioningConnectionInventory) => void;
    let signal: AbortSignal | undefined;
    const oldList = vi.fn((requestSignal?: AbortSignal) => {
      signal = requestSignal;
      return new Promise<CommissioningConnectionInventory>((resolve) => {
        resolveOld = resolve;
      });
    });
    const oldRepository = repositoryWith(oldList);
    const nextRepository = repositoryWith(vi.fn().mockResolvedValue({ ...inventory, nodeId: "new-edge" }));
    const receive = vi.fn();
    const { rerender, unmount } = renderHook(
      ({ repository }) => useLiveConnections(repository, true, receive, vi.fn()),
      { initialProps: { repository: oldRepository } },
    );
    act(() => {
      window.dispatchEvent(new Event("focus"));
      window.dispatchEvent(new Event("focus"));
    });
    expect(oldList).toHaveBeenCalledTimes(1);
    await act(async () => {
      rerender({ repository: nextRepository });
    });
    expect(signal?.aborted).toBe(true);
    await act(async () => {
      resolveOld(inventory);
    });
    expect(receive).toHaveBeenCalledTimes(1);
    expect(receive).toHaveBeenCalledWith(expect.objectContaining({ nodeId: "new-edge" }));
    unmount();
  });
});
