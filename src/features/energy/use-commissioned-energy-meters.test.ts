import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CommissioningSession } from "@/features/equipment/commissioning-repository";

const state = vi.hoisted(() => ({ list: vi.fn() }));
vi.mock("@/features/equipment/commissioning-repository", () => ({
  HttpCommissioningRepository: class {
    listSessions = state.list;
  },
}));
vi.mock("@/lib/telemetry/runtime-config", () => ({
  getTelemetryRuntimeConfig: () => ({ mode: "live", apiBaseUrl: "http://127.0.0.1:8082" }),
}));
vi.mock("@/features/security/security-session", () => ({ createAuthenticatedFetch: () => vi.fn() }));
vi.mock("@/features/security/supabase-auth", () => ({ createRuntimeCredentialProvider: () => vi.fn() }));
import { useCommissionedEnergyMeters } from "./use-commissioned-energy-meters";

function active(name: string): CommissioningSession {
  return {
    lifecycle: "active",
    profileId: "eastron-sdm120m",
    profileVersion: "eastron-sdm120m-fc04-v1",
    nodeId: "edge-01",
    busId: "commissioning-0123456789abcdef",
    unitId: 1,
    displayName: name,
  } as CommissioningSession;
}

describe("authorized commissioned meter inventory", () => {
  beforeEach(() => vi.resetAllMocks());
  it("discards an old organization's late response and fails closed while switching", async () => {
    let resolveA!: (value: CommissioningSession[]) => void;
    state.list.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveA = resolve;
        }),
    );
    state.list.mockResolvedValueOnce([active("Organization B")]);
    const { result, rerender } = renderHook(({ org }) => useCommissionedEnergyMeters(true, org, "user"), {
      initialProps: { org: "org-a" },
    });
    await waitFor(() => expect(state.list).toHaveBeenCalledTimes(1));
    rerender({ org: "org-b" });
    expect(result.current.meters).toEqual([]);
    await waitFor(() => expect(result.current.meters[0]?.label).toBe("Organization B"));
    await act(async () => resolveA([active("Organization A")]));
    expect(result.current.meters.map((meter) => meter.label)).toEqual(["Organization B"]);
  });
  it("reports permission or service errors without preserving previous scoped meters", async () => {
    state.list.mockRejectedValueOnce(new Error("forbidden"));
    const { result } = renderHook(() => useCommissionedEnergyMeters(true, "org-a", "user"));
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.meters).toEqual([]);
  });
});
