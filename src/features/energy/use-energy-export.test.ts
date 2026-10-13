import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EnergyExportJob, EnergyExportOptions } from "./energy-export-client";
import { useEnergyExport } from "./use-energy-export";

const mocks = vi.hoisted(() => ({ construct: vi.fn() }));
vi.mock("./energy-export-client", async (original) => ({
  ...(await original<typeof import("./energy-export-client")>()),
  EnergyExportClient: vi.fn(function () {
    return mocks.construct();
  }),
}));
vi.mock("@/lib/telemetry/runtime-config", () => ({
  getTelemetryRuntimeConfig: () => ({
    mode: "live",
    apiBaseUrl: "http://synthetic.example.test",
    websocketUrl: "ws://synthetic.example.test",
  }),
}));

const options: EnergyExportOptions = {
  series: [
    {
      node_id: "edge-01",
      equipment_id: "LE01MP-200",
      channel_id: "200-voltage",
      metric: "electrical.voltage",
      unit: "V",
    },
  ],
  from: "2026-07-23T09:00:00Z",
  to: "2026-07-23T10:00:00Z",
  step_seconds: 0,
  statistics: ["avg"],
  format: "xlsx",
};
function job(id: string): EnergyExportJob {
  return {
    job_id: id.repeat(32),
    status: "queued",
    phase: "preview",
    created_at: "2026-10-13T10:00:00Z",
    expires_at: "2026-10-13T11:00:00Z",
    options,
    progress: { processed: 0, total: null, unit: "source_events" },
    preview: null,
    artifact: null,
    error: null,
  };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
beforeEach(() => {
  sessionStorage.clear();
  mocks.construct.mockReset();
});
afterEach(() => {
  sessionStorage.clear();
  vi.clearAllMocks();
});

describe("Energy export identity and request lifecycle", () => {
  it("aborts and rejects a previous owner's late status after organization/identity changes", async () => {
    const pending = deferred<EnergyExportJob>();
    const firstJob = job("a"),
      secondJob = job("b");
    const first = {
      preview: vi.fn().mockResolvedValue(firstJob),
      job: vi.fn().mockReturnValue(pending.promise),
    };
    const second = {
      preview: vi.fn().mockResolvedValue(secondJob),
      job: vi.fn().mockResolvedValue({
        ...secondJob,
        status: "failed",
        error: { code: "fixture", message: "Synthetic terminal status" },
      }),
    };
    mocks.construct.mockReturnValueOnce(first).mockReturnValueOnce(second);
    const { result, rerender } = renderHook((props) => useEnergyExport(props), {
      initialProps: { enabled: true, organizationId: "org-a", securityScopeId: "identity-a" },
    });
    await act(async () => {
      await result.current.preview(options);
    });
    await waitFor(() => expect(first.job).toHaveBeenCalled());
    const oldSignal = first.job.mock.calls[0][1] as AbortSignal;
    rerender({ enabled: true, organizationId: "org-b", securityScopeId: "identity-b" });
    expect(result.current.job).toBeNull();
    expect(oldSignal.aborted).toBe(true);
    await act(async () => {
      await result.current.preview(options);
    });
    await act(async () => pending.resolve({ ...firstJob, status: "preview_ready" }));
    expect(result.current.job?.job_id).toBe(secondJob.job_id);
    expect(result.current.job?.job_id).not.toBe(firstJob.job_id);
  });
  it("keeps cancellation terminal when an older poll response arrives", async () => {
    const pending = deferred<EnergyExportJob>();
    const original = job("c");
    const api = {
      preview: vi.fn().mockResolvedValue(original),
      job: vi.fn().mockReturnValue(pending.promise),
      action: vi.fn().mockResolvedValue({ ...original, status: "canceled" }),
    };
    mocks.construct.mockReturnValue(api);
    const { result } = renderHook(() =>
      useEnergyExport({ enabled: true, organizationId: "org-a", securityScopeId: "identity-a" }),
    );
    await act(async () => {
      await result.current.preview(options);
    });
    await waitFor(() => expect(api.job).toHaveBeenCalled());
    await act(async () => {
      await result.current.cancel();
    });
    await act(async () => pending.resolve({ ...original, status: "running" }));
    expect(result.current.job?.status).toBe("canceled");
    expect(sessionStorage.getItem('nexolab:energy-export:["org-a","identity-a"]')).toBeNull();
  });
});
