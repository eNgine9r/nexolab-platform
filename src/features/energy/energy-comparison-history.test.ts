import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  loadEnergyComparisonHistory,
  mergeEnergyComparisonHistory,
  readEnergyComparisonHistory,
  retainEnergyComparisonHistory,
} from "./energy-comparison-history";
import { readRetainedEnergyHistory, resetRetainedEnergyHistoryForTests } from "./energy-history-retention";
import { ENERGY_METRICS, type EnergyMetricId } from "./energy-telemetry";
import { isEnergyHistorySegmentStart } from "./energy-history-segment";
import type { TelemetryAdapter, TelemetrySample } from "@/lib/telemetry/types";

const snapshot = "2026-10-13T10:00:00.000Z";
const window = { nodeId: "edge-01", from: new Date("2026-10-13T08:00:00Z"), to: new Date(snapshot) };
const key = { securityScope: "user:organization", nodeId: "edge-01", metric: "", range: "1h" };
function sample(metric: EnergyMetricId, value = 230, at = "2026-10-13T09:00:00.000Z"): TelemetrySample {
  return {
    event_id: `${metric}:${at}:${value}`,
    node_id: "edge-01",
    equipment_id: "LE01MP-200",
    channel_id: `200-${metric}`,
    captured_at: at,
    received_at: snapshot,
    metric,
    value,
    unit: ENERGY_METRICS.find((item) => item.id === metric)!.expectedUnit,
    quality: "valid",
    source: "modbus",
    alarm: null,
    raw_value: null,
    raw_status: null,
  };
}
beforeEach(resetRetainedEnergyHistoryForTests);

describe("Energy multi-metric history", () => {
  it("shares one watermark, bounds parallel REST reads and never subscribes", async () => {
    let active = 0;
    let maximum = 0;
    const history = vi.fn<TelemetryAdapter["history"]>(async (filters) => {
      active++;
      maximum = Math.max(maximum, active);
      await new Promise((resolve) => setTimeout(resolve, 5));
      active--;
      return {
        items: [sample(filters.metric as EnergyMetricId)],
        count: 1,
        limit: 1000,
        offset: 0,
        next_offset: null,
        snapshot_at: snapshot,
      };
    });
    const subscribe = vi.fn();
    const result = await loadEnergyComparisonHistory(
      { history, subscribe } as unknown as TelemetryAdapter,
      window,
      ["electrical.power.active", "electrical.voltage", "electrical.current", "electrical.frequency"],
    );
    expect(result.errors).toEqual({});
    expect(result.samples).toHaveLength(4);
    expect(maximum).toBe(2);
    expect(history.mock.calls[0][0].snapshot_at).toBeUndefined();
    expect(history.mock.calls.slice(1).every(([filters]) => filters.snapshot_at === snapshot)).toBe(true);
    expect(
      history.mock.calls.every(
        ([filters]) =>
          filters.from === window.from && new Date(filters.to ?? 0).getTime() === window.to.getTime(),
      ),
    ).toBe(true);
    expect(subscribe).not.toHaveBeenCalled();
  });

  it("reports failed metrics while preserving other persisted series", async () => {
    const history = vi.fn<TelemetryAdapter["history"]>(async (filters) => {
      if (filters.metric === "electrical.voltage") throw new Error("history unavailable");
      return {
        items: [sample(filters.metric as EnergyMetricId)],
        count: 1,
        limit: 1000,
        offset: 0,
        next_offset: null,
        snapshot_at: snapshot,
      };
    });
    const result = await loadEnergyComparisonHistory({ history } as unknown as TelemetryAdapter, window, [
      "electrical.power.active",
      "electrical.voltage",
      "electrical.current",
    ]);
    expect(result.samples.map((item) => item.metric)).toEqual([
      "electrical.power.active",
      "electrical.current",
    ]);
    expect(result.errors).toEqual({ "electrical.voltage": "history unavailable" });
  });

  it("fails closed across metrics if no valid common snapshot can be established", async () => {
    const history = vi.fn<TelemetryAdapter["history"]>(async () => {
      throw new Error("database unavailable");
    });
    const result = await loadEnergyComparisonHistory({ history } as unknown as TelemetryAdapter, window, [
      "electrical.power.active",
      "electrical.voltage",
      "electrical.current",
    ]);
    expect(result.samples).toEqual([]);
    expect(Object.keys(result.errors)).toHaveLength(3);
    expect(history).toHaveBeenCalledOnce();
  });

  it("does not cache failed metrics or leak another identity's retained history", () => {
    const metrics: EnergyMetricId[] = ["electrical.power.active", "electrical.voltage"];
    retainEnergyComparisonHistory(
      key,
      metrics,
      {
        window: { from: window.from.toISOString(), to: window.to.toISOString() },
        loadedThrough: snapshot,
        cadenceAuthorityFingerprint: "revision1",
        samples: metrics.map((metric) => sample(metric)),
      },
      { "electrical.voltage": "unavailable" },
    );
    expect(readRetainedEnergyHistory({ ...key, metric: metrics[0] })?.samples).toHaveLength(1);
    expect(readRetainedEnergyHistory({ ...key, metric: metrics[1] })).toBeNull();
    expect(readEnergyComparisonHistory(key, metrics)).toBeNull();
    expect(readEnergyComparisonHistory({ ...key, securityScope: "another:user" }, [metrics[0]])).toBeNull();
  });

  it("keeps invalid-quality breaks independent for metrics from the same meter", () => {
    const power = sample("electrical.power.active", 400, "2026-10-13T09:00:00Z");
    const invalid = {
      ...sample("electrical.voltage", 230, power.captured_at),
      quality: "sensor_error" as const,
      value: null,
    };
    const voltage = sample("electrical.voltage", 231, "2026-10-13T09:00:30Z");
    const baselineVoltage = sample("electrical.voltage", 229, "2026-10-13T08:59:30Z");
    const result = mergeEnergyComparisonHistory(
      [],
      [baselineVoltage, power, invalid, voltage],
      window,
      ["electrical.power.active", "electrical.voltage"],
      null,
    );
    expect(isEnergyHistorySegmentStart(result.find((item) => item.metric === power.metric)!.event_id)).toBe(
      false,
    );
    expect(isEnergyHistorySegmentStart(result.find((item) => item.value === 231)!.event_id)).toBe(true);
  });
});
