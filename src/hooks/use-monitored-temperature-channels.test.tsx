import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/features/security/security-session", () => ({ createAuthenticatedFetch: () => mocks.fetch }));
vi.mock("@/features/security/supabase-auth", () => ({ createRuntimeCredentialProvider: vi.fn() }));
import { useMonitoredTemperatureChannels } from "./use-monitored-temperature-channels";

const registry = {
  schema_version: 2,
  revision: 46,
  buses: [{ bus_id: "bus", protocol: "modbus_rtu", read_only: true }],
  devices: [
    {
      device_id: "xjp60d-sections:bus:7",
      bus_id: "bus",
      unit_id: 7,
      device_family: "xjp60d",
      lifecycle: "active",
    },
  ],
  targets: [
    {
      device_id: "xjp60d-sections:bus:7",
      target_id: "xjp60d-sections:bus:7-S01",
      telemetry_channel_id: "bus:7-S01",
      metric: "temperature.probe",
      unit: "degC",
      function: 3,
      lifecycle: "active",
      poll_eligible: true,
    },
  ],
};

describe("Overview monitoring read", () => {
  beforeEach(() => {
    mocks.fetch.mockReset();
  });
  it("uses authenticated GET only and loads a canonical section channel", async () => {
    mocks.fetch.mockResolvedValue(Response.json(registry));
    const { result } = renderHook(() =>
      useMonitoredTemperatureChannels({ enabled: true, organizationId: "a" }),
    );
    await waitFor(() => expect(result.current.channelIds).toEqual(["bus:7-S01"]));
    expect(mocks.fetch).toHaveBeenCalledTimes(1);
    expect(mocks.fetch.mock.calls[0]).toEqual([
      "/api/device-agent/acquisition-registry",
      expect.objectContaining({ method: "GET" }),
    ]);
  });
  it("does not reuse another organization's channels or fall back after a denied read", async () => {
    mocks.fetch
      .mockResolvedValueOnce(Response.json(registry))
      .mockResolvedValueOnce(new Response(null, { status: 403 }));
    const { result, rerender } = renderHook(
      (organizationId) => useMonitoredTemperatureChannels({ enabled: true, organizationId }),
      { initialProps: "a" },
    );
    await waitFor(() => expect(result.current.channelIds).toHaveLength(1));
    rerender("b");
    expect(result.current.channelIds).toEqual([]);
    await waitFor(() => expect(result.current.error).toContain("403"));
    expect(result.current.channelIds).toEqual([]);
  });
  it("makes no request while disabled and discards an in-flight result on sign-out", async () => {
    let resolve!: (response: Response) => void;
    mocks.fetch.mockImplementation(
      () =>
        new Promise<Response>((r) => {
          resolve = r;
        }),
    );
    const { result, rerender } = renderHook(
      (enabled) => useMonitoredTemperatureChannels({ enabled, organizationId: "a" }),
      { initialProps: false },
    );
    expect(mocks.fetch).not.toHaveBeenCalled();
    rerender(true);
    rerender(false);
    resolve(Response.json(registry));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.channelIds).toEqual([]);
  });
});
