import type { LiveDashboardInventoryClient } from "./inventory-client";
import type { LiveDashboardInventoryItem } from "./types";

const INVENTORY_PAGE_SIZE = 500;
const MAX_INVENTORY_PAGES = 20;

export function liveDashboardInventoryKey(
  item: Pick<LiveDashboardInventoryItem, "channel_id" | "metric">,
): string {
  return `${encodeURIComponent(item.channel_id)}|${encodeURIComponent(item.metric)}`;
}

export async function loadLiveDashboardInventory(
  client: LiveDashboardInventoryClient,
  signal?: AbortSignal,
): Promise<LiveDashboardInventoryItem[]> {
  const inventory = new Map<string, LiveDashboardInventoryItem>();
  let offset = 0;

  for (let page = 0; page < MAX_INVENTORY_PAGES; page += 1) {
    const response = await client.list({ limit: INVENTORY_PAGE_SIZE, offset }, signal);
    for (const item of response.items) inventory.set(item.key, item);
    if (!response.has_more) {
      return [...inventory.values()].sort(
        (left, right) =>
          left.node_id.localeCompare(right.node_id, "uk-UA") ||
          left.equipment_id.localeCompare(right.equipment_id, "uk-UA") ||
          left.channel_id.localeCompare(right.channel_id, "uk-UA") ||
          left.metric.localeCompare(right.metric, "uk-UA") ||
          left.channel_ref_id.localeCompare(right.channel_ref_id, "uk-UA"),
      );
    }
    const nextOffset = response.offset + response.items.length;
    if (response.items.length === 0 || nextOffset <= offset) {
      throw new Error("Live Dashboard inventory pagination did not advance.");
    }
    offset = nextOffset;
  }

  throw new Error("Live Dashboard inventory exceeded the bounded 10,000-channel window.");
}
