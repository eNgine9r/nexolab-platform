import type { TelemetryAdapter, TelemetrySample } from "@/lib/telemetry/types";

import type { LiveDashboardInventoryItem } from "./types";

const INVENTORY_PAGE_SIZE = 1_000;
const MAX_INVENTORY_PAGES = 20;

export function liveDashboardInventoryKey(item: Pick<TelemetrySample, "channel_id" | "metric">): string {
  return `${encodeURIComponent(item.channel_id)}|${encodeURIComponent(item.metric)}`;
}

function timestamp(sample: TelemetrySample): number {
  const captured = Date.parse(sample.captured_at);
  const received = sample.received_at ? Date.parse(sample.received_at) : Number.NEGATIVE_INFINITY;
  return Number.isFinite(captured) ? captured : received;
}

export function inventoryFromLatestSamples(
  samples: readonly TelemetrySample[],
): LiveDashboardInventoryItem[] {
  const latest = new Map<string, TelemetrySample>();
  for (const sample of samples) {
    const key = liveDashboardInventoryKey(sample);
    const current = latest.get(key);
    if (!current || timestamp(current) <= timestamp(sample)) latest.set(key, sample);
  }
  return [...latest.entries()]
    .map(([key, sample]) => ({
      key,
      node_id: sample.node_id,
      equipment_id: sample.equipment_id,
      channel_id: sample.channel_id,
      metric: sample.metric,
      native_unit: sample.unit,
      source: sample.source,
      quality: sample.quality,
      alarm: sample.alarm,
      latest: sample,
    }))
    .sort(
      (left, right) =>
        left.node_id.localeCompare(right.node_id, "uk-UA") ||
        left.equipment_id.localeCompare(right.equipment_id, "uk-UA") ||
        left.channel_id.localeCompare(right.channel_id, "uk-UA") ||
        left.metric.localeCompare(right.metric, "uk-UA"),
    );
}

export async function loadLiveDashboardInventory(
  adapter: TelemetryAdapter,
  signal?: AbortSignal,
): Promise<LiveDashboardInventoryItem[]> {
  const samples = new Map<string, TelemetrySample>();
  let offset = 0;

  for (let page = 0; page < MAX_INVENTORY_PAGES; page += 1) {
    const response = await adapter.latest({ limit: INVENTORY_PAGE_SIZE, offset }, signal);
    for (const sample of response.items) {
      const current = samples.get(sample.event_id);
      if (!current || timestamp(current) <= timestamp(sample)) samples.set(sample.event_id, sample);
    }
    if (response.next_offset === null) return inventoryFromLatestSamples([...samples.values()]);
    if (response.next_offset <= offset)
      throw new Error("Live Dashboard inventory pagination did not advance.");
    offset = response.next_offset;
  }

  throw new Error("Live Dashboard inventory exceeded the bounded 20,000-sample window.");
}
