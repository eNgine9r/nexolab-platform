import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CommissionedEnergyMeter } from "./energy-commissioned-meters";
import type { TelemetrySample } from "@/lib/telemetry/types";

const state = vi.hoisted(() => ({ history: vi.fn() }));
vi.mock("@/lib/telemetry/runtime-config", () => ({ getTelemetryRuntimeConfig: () => ({ mode: "live" }) }));
vi.mock("@/features/security/security-session", () => ({ createAuthenticatedFetch: () => vi.fn() }));
vi.mock("@/features/security/supabase-auth", () => ({ createRuntimeCredentialProvider: () => vi.fn() }));
vi.mock("@/lib/telemetry/create-adapter", () => ({
  createTelemetryAdapter: () => ({ history: state.history }),
}));

import { useEnergyConsumption } from "./use-energy-consumption";

describe("commissioned meter consumption", () => {
  beforeEach(() => vi.clearAllMocks());

  it("uses only each authorized bus and node for both counter boundaries", async () => {
    const meters: CommissionedEnergyMeter[] = ["0123456789abcdef", "fedcba9876543210"].map((id) => ({
      nodeId: "edge-01",
      busId: `commissioning-${id}`,
      unitId: 1,
      equipmentId: `SDM120M:commissioning-${id}:1`,
      label: id,
      modelLabel: "SDM",
      family: "sdm120",
    }));
    const reading = (
      meter: CommissionedEnergyMeter,
      event: string,
      at: string,
      value: number,
      node = "edge-01",
    ): TelemetrySample => ({
      event_id: event,
      node_id: node,
      captured_at: at,
      metric: "electrical.energy.active",
      value,
      unit: "kWh",
      quality: "valid",
      source: "eastron-sdm120m",
      equipment_id: meter.equipmentId,
      channel_id: "1-energy-active",
      alarm: null,
      raw_value: null,
      raw_status: null,
    });
    const items = [
      reading(meters[0], "a0", "2026-08-17T07:59:00Z", 100),
      reading(meters[0], "a1", "2026-08-17T11:59:00Z", 110),
      reading(meters[1], "b0", "2026-08-17T07:59:00Z", 200),
      reading(meters[1], "b1", "2026-08-17T11:59:00Z", 220),
      reading(meters[0], "foreign", "2026-08-17T11:59:30Z", 9999, "edge-02"),
    ];
    state.history.mockResolvedValue({ items });
    const { result } = renderHook(() =>
      useEnergyConsumption({
        enabled: true,
        organizationId: "org-a",
        securityScopeId: "u",
        commissionedMeters: meters,
      }),
    );
    const window = { from: new Date("2026-08-17T08:00:00Z"), to: new Date("2026-08-17T12:00:00Z") };
    expect(await result.current.load(meters[0], window, null)).toMatchObject({
      status: "ready",
      valueKwh: 10,
    });
    expect(await result.current.load(meters[1], window, null)).toMatchObject({
      status: "ready",
      valueKwh: 20,
    });
    expect(await result.current.load({ ...meters[0], nodeId: "edge-02" }, window, null)).toMatchObject({
      status: "error",
      valueKwh: null,
    });
    expect(state.history.mock.calls.every(([query]) => query.node_id === "edge-01")).toBe(true);
  });
});
