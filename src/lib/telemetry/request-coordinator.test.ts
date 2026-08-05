import { describe, expect, it, vi } from "vitest";

import { TelemetryRequestCoordinator } from "./request-coordinator";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

async function flushPromises(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

describe("TelemetryRequestCoordinator", () => {
  it("shares one physical request between identical concurrent consumers", async () => {
    const coordinator = new TelemetryRequestCoordinator();
    const result = deferred<string>();
    const factory = vi.fn(() => result.promise);

    const first = coordinator.request("latest:edge-01", undefined, factory);
    const second = coordinator.request("latest:edge-01", undefined, factory);

    expect(factory).toHaveBeenCalledTimes(1);
    expect(coordinator.inFlightCount).toBe(1);
    expect(coordinator.hasConsumers).toBe(true);

    result.resolve("ready");
    await expect(first).resolves.toBe("ready");
    await expect(second).resolves.toBe("ready");
    await flushPromises();

    expect(coordinator.inFlightCount).toBe(0);
    expect(coordinator.hasConsumers).toBe(false);
  });

  it("keeps the physical request alive when only one consumer aborts", async () => {
    const coordinator = new TelemetryRequestCoordinator();
    const result = deferred<string>();
    let physicalSignal: AbortSignal | null = null;
    const factory = vi.fn((signal: AbortSignal) => {
      physicalSignal = signal;
      return result.promise;
    });
    const firstController = new AbortController();
    const secondController = new AbortController();

    const first = coordinator.request("history:24h", firstController.signal, factory);
    const second = coordinator.request("history:24h", secondController.signal, factory);
    firstController.abort("route unmounted");

    await expect(first).rejects.toMatchObject({ code: "aborted" });
    expect(physicalSignal?.aborted).toBe(false);
    expect(coordinator.hasConsumers).toBe(true);

    result.resolve("history");
    await expect(second).resolves.toBe("history");
    expect(factory).toHaveBeenCalledTimes(1);
  });

  it("aborts the physical request after the final consumer releases it", async () => {
    const coordinator = new TelemetryRequestCoordinator();
    const firstController = new AbortController();
    const secondController = new AbortController();
    let physicalSignal: AbortSignal | null = null;
    const factory = vi.fn(
      (signal: AbortSignal) =>
        new Promise<string>((_resolve, reject) => {
          physicalSignal = signal;
          signal.addEventListener("abort", () => reject(signal.reason), { once: true });
        }),
    );

    const first = coordinator.request("latest:shared", firstController.signal, factory);
    const second = coordinator.request("latest:shared", secondController.signal, factory);
    firstController.abort("first route closed");
    await expect(first).rejects.toMatchObject({ code: "aborted" });
    expect(physicalSignal?.aborted).toBe(false);

    secondController.abort("last route closed");
    await expect(second).rejects.toMatchObject({ code: "aborted" });
    expect(physicalSignal?.aborted).toBe(true);
    await flushPromises();
    expect(coordinator.inFlightCount).toBe(0);
  });

  it("removes settled and failed entries so later calls can start cleanly", async () => {
    const coordinator = new TelemetryRequestCoordinator();
    const factory = vi
      .fn<(signal: AbortSignal) => Promise<string>>()
      .mockRejectedValueOnce(new Error("temporary failure"))
      .mockResolvedValueOnce("recovered");

    await expect(coordinator.request("latest:retry", undefined, factory)).rejects.toThrow(
      "temporary failure",
    );
    await flushPromises();
    expect(coordinator.inFlightCount).toBe(0);

    await expect(coordinator.request("latest:retry", undefined, factory)).resolves.toBe("recovered");
    await flushPromises();
    expect(factory).toHaveBeenCalledTimes(2);
    expect(coordinator.inFlightCount).toBe(0);
  });
});
