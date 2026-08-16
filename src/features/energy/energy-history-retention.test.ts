import { beforeEach, describe, expect, it } from "vitest";

import type { TelemetrySample } from "@/lib/telemetry/types";

import {
  ENERGY_HISTORY_RECONCILIATION_OVERLAP_MS,
  ENERGY_HISTORY_RETENTION_TTL_MS,
  invalidateIncompatibleRetainedEnergyHistory,
  invalidateRetainedEnergyHistory,
  readRetainedEnergyHistory,
  resetRetainedEnergyHistoryForTests,
  retainEnergyHistory,
  type EnergyHistoryRetentionKey,
} from "./energy-history-retention";

const KEY: EnergyHistoryRetentionKey = {
  securityScope: "user-a:org-a",
  nodeId: "edge-01",
  metric: "electrical.power.active",
  range: "24h",
};

const SAMPLE: TelemetrySample = {
  event_id: "event-1",
  node_id: "edge-01",
  captured_at: "2026-08-16T20:00:00.000Z",
  metric: "electrical.power.active",
  value: 420,
  unit: "W",
  quality: "valid",
  source: "modbus",
  equipment_id: "LE01MP-200",
  channel_id: "200-power-active",
  alarm: null,
  raw_value: 420,
  raw_status: 0,
  received_at: "2026-08-16T20:00:00.100Z",
};

const VALUE = {
  window: {
    from: "2026-08-15T20:00:00.000Z",
    to: "2026-08-16T20:00:00.000Z",
  },
  loadedThrough: "2026-08-16T20:00:00.000Z",
  samples: [SAMPLE],
};

describe("Energy history retention", () => {
  beforeEach(() => {
    resetRetainedEnergyHistoryForTests();
  });

  it("uses a bounded delayed-ingestion overlap smaller than the retention lifetime", () => {
    expect(ENERGY_HISTORY_RECONCILIATION_OVERLAP_MS).toBeGreaterThan(0);
    expect(ENERGY_HISTORY_RECONCILIATION_OVERLAP_MS).toBeLessThan(ENERGY_HISTORY_RETENTION_TTL_MS);
  });

  it("retains a defensive copy for the exact security, node, metric and range key", () => {
    retainEnergyHistory(KEY, VALUE, 1_000);

    const retained = readRetainedEnergyHistory(KEY, 1_001);
    expect(retained).toEqual(VALUE);

    retained!.samples[0].value = 999;
    retained!.window.to = "2030-01-01T00:00:00.000Z";

    expect(readRetainedEnergyHistory(KEY, 1_002)).toEqual(VALUE);
  });

  it("does not leak retained history across organization, identity, metric or range scopes", () => {
    retainEnergyHistory(KEY, VALUE, 1_000);

    const variants: EnergyHistoryRetentionKey[] = [
      { ...KEY, securityScope: "user-a:org-b" },
      { ...KEY, securityScope: "user-b:org-a" },
      { ...KEY, nodeId: "edge-02" },
      { ...KEY, metric: "electrical.voltage" },
      { ...KEY, range: "6h" },
    ];

    for (const variant of variants) {
      expect(readRetainedEnergyHistory(variant, 1_001)).toBeNull();
    }
  });

  it("expires retained history after the application-memory TTL", () => {
    retainEnergyHistory(KEY, VALUE, 1_000);

    expect(readRetainedEnergyHistory(KEY, 1_000 + ENERGY_HISTORY_RETENTION_TTL_MS)).not.toBeNull();
    expect(readRetainedEnergyHistory(KEY, 1_001 + ENERGY_HISTORY_RETENTION_TTL_MS)).toBeNull();
  });

  it("invalidates one entry for explicit history retry", () => {
    retainEnergyHistory(KEY, VALUE, 1_000);
    invalidateRetainedEnergyHistory(KEY);
    expect(readRetainedEnergyHistory(KEY, 1_001)).toBeNull();
  });

  it("removes entries from incompatible security scopes while preserving the current scope", () => {
    const otherScope = { ...KEY, securityScope: "user-b:org-b" };
    retainEnergyHistory(KEY, VALUE, 1_000);
    retainEnergyHistory(otherScope, VALUE, 1_000);

    invalidateIncompatibleRetainedEnergyHistory(KEY.securityScope);

    expect(readRetainedEnergyHistory(KEY, 1_001)).not.toBeNull();
    expect(readRetainedEnergyHistory(otherScope, 1_001)).toBeNull();
  });
});
