import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearAllMonitoringReadModels,
  clearMonitoringReadModelScope,
  inspectMonitoringReadModelCache,
  inspectMonitoringReadModelRequestCount,
  invalidateMonitoringReadModel,
  peekMonitoringReadModel,
  readMonitoringReadModel,
  refreshMonitoringReadModel,
  subscribeMonitoringReadModel,
} from "./monitoring-read-model-cache";

const scope = "http://nexolab.local|org-a";
const options = { freshTtlMs: 1_000, staleTtlMs: 10_000, maxEntriesPerScope: 2 };

beforeEach(() => {
  clearAllMonitoringReadModels();
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-08-13T09:00:00Z"));
});

afterEach(() => {
  clearAllMonitoringReadModels();
  vi.useRealTimers();
});

describe("monitoring read-model cache", () => {
  it("deduplicates concurrent equivalent reads", async () => {
    let resolve!: (value: string) => void;
    const loader = vi.fn(
      () =>
        new Promise<string>((nextResolve) => {
          resolve = nextResolve;
        }),
    );

    const first = readMonitoringReadModel(scope, "nodes:list", loader, options);
    const second = readMonitoringReadModel(scope, "nodes:list", loader, options);
    await Promise.resolve();

    expect(loader).toHaveBeenCalledTimes(1);
    expect(inspectMonitoringReadModelRequestCount(scope, "nodes:list")).toBe(1);

    resolve("ready");
    await expect(first).resolves.toBe("ready");
    await expect(second).resolves.toBe("ready");
  });

  it("serves a fresh value without another request", async () => {
    const loader = vi.fn().mockResolvedValue("first");

    await expect(readMonitoringReadModel(scope, "sessions:list", loader, options)).resolves.toBe("first");
    await expect(readMonitoringReadModel(scope, "sessions:list", loader, options)).resolves.toBe("first");

    expect(loader).toHaveBeenCalledTimes(1);
    expect(peekMonitoringReadModel<string>(scope, "sessions:list", options)).toMatchObject({
      value: "first",
      freshness: "fresh",
      error: null,
    });
  });

  it("returns stale content immediately and reconciles it in the background", async () => {
    await readMonitoringReadModel(scope, "layouts:catalog", () => Promise.resolve("v1"), options);
    vi.advanceTimersByTime(1_500);

    const refreshed = vi.fn().mockResolvedValue("v2");
    await expect(readMonitoringReadModel(scope, "layouts:catalog", refreshed, options)).resolves.toBe("v1");
    await Promise.resolve();
    await Promise.resolve();

    expect(refreshed).toHaveBeenCalledTimes(1);
    expect(peekMonitoringReadModel<string>(scope, "layouts:catalog", options)).toMatchObject({
      value: "v2",
      freshness: "fresh",
      error: null,
    });
  });

  it("preserves a stale value and records a background refresh failure", async () => {
    await readMonitoringReadModel(scope, "inventory", () => Promise.resolve("known"), options);
    vi.advanceTimersByTime(1_500);

    await expect(
      readMonitoringReadModel(scope, "inventory", () => Promise.reject(new Error("offline")), options),
    ).resolves.toBe("known");
    await Promise.resolve();
    await Promise.resolve();

    const snapshot = peekMonitoringReadModel<string>(scope, "inventory", options);
    expect(snapshot.value).toBe("known");
    expect(snapshot.freshness).toBe("stale");
    expect(snapshot.error?.message).toBe("offline");
  });

  it("notifies subscribers after refresh and targeted invalidation", async () => {
    const listener = vi.fn();
    const unsubscribe = subscribeMonitoringReadModel(scope, "equipment:catalog", listener);

    await refreshMonitoringReadModel(scope, "equipment:catalog", () => Promise.resolve(["K106"]), options);
    expect(listener).toHaveBeenCalled();
    listener.mockClear();

    invalidateMonitoringReadModel(scope, "equipment:");
    expect(listener).toHaveBeenCalledTimes(1);
    expect(peekMonitoringReadModel(scope, "equipment:catalog", options).value).toBeNull();

    unsubscribe();
  });

  it("bounds entries by least-recently-touched order", async () => {
    await readMonitoringReadModel(scope, "a", () => Promise.resolve("A"), options);
    vi.advanceTimersByTime(10);
    await readMonitoringReadModel(scope, "b", () => Promise.resolve("B"), options);
    vi.advanceTimersByTime(10);
    await readMonitoringReadModel(scope, "c", () => Promise.resolve("C"), options);

    expect(peekMonitoringReadModel(scope, "a", options).value).toBeNull();
    expect(peekMonitoringReadModel<string>(scope, "b", options).value).toBe("B");
    expect(peekMonitoringReadModel<string>(scope, "c", options).value).toBe("C");
    expect(inspectMonitoringReadModelCache().entries).toBe(2);
  });

  it("clears organization-scoped data deterministically", async () => {
    await readMonitoringReadModel(scope, "nodes:list", () => Promise.resolve(["edge-01"]), options);
    await readMonitoringReadModel("http://nexolab.local|org-b", "nodes:list", () => Promise.resolve(["edge-02"]), options);

    clearMonitoringReadModelScope(scope);

    expect(peekMonitoringReadModel(scope, "nodes:list", options).value).toBeNull();
    expect(
      peekMonitoringReadModel<string[]>("http://nexolab.local|org-b", "nodes:list", options).value,
    ).toEqual(["edge-02"]);
  });
});
