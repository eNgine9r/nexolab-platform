import { describe, expect, it, vi } from "vitest";

import type { TelemetryHistoryQuery, TelemetrySample } from "@/lib/telemetry/types";

import { CADENCE_PROBE_LOOKBACK_MS, probeLiveChannelCadence } from "./cadence-probe";
import { CADENCE_OBSERVATION_LIMIT, liveFreshnessFor, observedCadenceMs } from "./freshness";
import { liveChannelKey } from "./live-telemetry";

const NOW = Date.parse("2026-11-21T12:00:00.000Z");

function sample(
  channel: string,
  capturedAtMs: number,
  overrides: Partial<TelemetrySample> = {},
): TelemetrySample {
  return {
    event_id: `${channel}-${capturedAtMs}`,
    node_id: "edge-01",
    captured_at: new Date(capturedAtMs).toISOString(),
    metric: "current",
    value: 12,
    unit: "mA",
    quality: "valid",
    source: "waveshare-8ai",
    equipment_id: "WAVESHARE-8AI-1",
    channel_id: channel,
    alarm: null,
    raw_value: 12000,
    raw_status: null,
    ...overrides,
  };
}

/** Persisted history fake: newest first, honouring filters and limit like the API. */
function historyAdapter(rows: TelemetrySample[], onCall?: (query: TelemetryHistoryQuery) => void) {
  return {
    history: vi.fn(async (query: TelemetryHistoryQuery) => {
      onCall?.(query);
      const items = rows
        .filter((row) => row.channel_id === query.channel_id && row.metric === query.metric)
        .sort((left, right) => Date.parse(right.captured_at) - Date.parse(left.captured_at))
        .slice(0, query.limit);
      return { items, count: items.length, limit: query.limit ?? 200, offset: 0, next_offset: null };
    }),
  };
}

describe("#1522 persisted cadence bootstrap", () => {
  it("learns a 60 s cadence immediately, so the first page view is not falsely stale", async () => {
    const rows = Array.from({ length: 10 }, (_, index) => sample("ch3", NOW - 45_000 - index * 60_000));
    const latest = rows[0];
    const observations = await probeLiveChannelCadence(historyAdapter(rows), [latest], { now: NOW });
    const key = liveChannelKey(latest);

    expect(observations[key]).toHaveLength(CADENCE_OBSERVATION_LIMIT);
    expect(observedCadenceMs(observations[key])).toBe(60_000);
    expect(liveFreshnessFor(latest, key, observations)).toMatchObject({
      basis: "observed_cadence",
      staleAfterMs: 105_000,
    });
  });

  it("requests only a tiny newest-first read-only page within the bounded look-back", async () => {
    const queries: TelemetryHistoryQuery[] = [];
    const rows = [sample("ch3", NOW - 1_000)];
    await probeLiveChannelCadence(
      historyAdapter(rows, (query) => queries.push(query)),
      rows,
      { now: NOW },
    );

    expect(queries).toHaveLength(1);
    expect(queries[0]).toMatchObject({
      node_id: "edge-01",
      equipment_id: "WAVESHARE-8AI-1",
      channel_id: "ch3",
      metric: "current",
      limit: CADENCE_OBSERVATION_LIMIT,
      offset: 0,
    });
    expect(Date.parse(String(queries[0].to)) - Date.parse(String(queries[0].from))).toBe(
      CADENCE_PROBE_LOOKBACK_MS,
    );
  });

  it("keeps channels independent and ignores rows of another unit identity", async () => {
    const slow = Array.from({ length: 4 }, (_, index) => sample("ch3", NOW - index * 60_000));
    const fast = Array.from({ length: 4 }, (_, index) => sample("ch4", NOW - index * 10_000));
    const otherUnit = sample("ch3", NOW - 5_000, { unit: "V", event_id: "other-unit" });
    const observations = await probeLiveChannelCadence(
      historyAdapter([...slow, ...fast, otherUnit]),
      [slow[0], fast[0]],
      { now: NOW },
    );
    expect(observedCadenceMs(observations[liveChannelKey(slow[0])])).toBe(60_000);
    expect(observedCadenceMs(observations[liveChannelKey(fast[0])])).toBe(10_000);
  });

  it("skips channels that already carry an authoritative server threshold", async () => {
    const adapter = historyAdapter([]);
    await probeLiveChannelCadence(adapter, [sample("ch3", NOW, { stale_after_seconds: 90 })], { now: NOW });
    expect(adapter.history).not.toHaveBeenCalled();
  });

  it("bounds the number of channels and the request concurrency", async () => {
    let inFlight = 0;
    let peak = 0;
    const adapter = {
      history: vi.fn(async () => {
        inFlight += 1;
        peak = Math.max(peak, inFlight);
        await new Promise((resolve) => setTimeout(resolve, 1));
        inFlight -= 1;
        return { items: [], count: 0, limit: 6, offset: 0, next_offset: null };
      }),
    };
    const latest = Array.from({ length: 20 }, (_, index) => sample(`ch${index}`, NOW));
    await probeLiveChannelCadence(adapter, latest, { now: NOW, maxChannels: 7, concurrency: 2 });
    expect(adapter.history).toHaveBeenCalledTimes(7);
    expect(peak).toBeLessThanOrEqual(2);
  });

  it("falls back silently on errors and stops after an authorization failure", async () => {
    const adapter = {
      history: vi.fn(async () => {
        throw Object.assign(new Error("forbidden"), { status: 403 });
      }),
    };
    const latest = Array.from({ length: 5 }, (_, index) => sample(`ch${index}`, NOW));
    await expect(probeLiveChannelCadence(adapter, latest, { now: NOW, concurrency: 1 })).resolves.toEqual({});
    expect(adapter.history).toHaveBeenCalledTimes(1);
  });

  it("ignores transient failures for one channel and still probes the others", async () => {
    const good = Array.from({ length: 3 }, (_, index) => sample("ok", NOW - index * 60_000));
    const base = historyAdapter(good);
    const adapter = {
      history: vi.fn(async (query: TelemetryHistoryQuery) => {
        if (query.channel_id === "broken") throw new Error("network");
        return base.history(query);
      }),
    };
    const observations = await probeLiveChannelCadence(adapter, [sample("broken", NOW), good[0]], {
      now: NOW,
      concurrency: 1,
    });
    expect(observedCadenceMs(observations[liveChannelKey(good[0])])).toBe(60_000);
  });

  it("stops when the page scope is aborted", async () => {
    const controller = new AbortController();
    const adapter = {
      history: vi.fn(async () => {
        controller.abort();
        throw new DOMException("aborted", "AbortError");
      }),
    };
    const latest = Array.from({ length: 4 }, (_, index) => sample(`ch${index}`, NOW));
    await probeLiveChannelCadence(adapter, latest, { now: NOW, signal: controller.signal, concurrency: 1 });
    expect(adapter.history).toHaveBeenCalledTimes(1);
  });
});
