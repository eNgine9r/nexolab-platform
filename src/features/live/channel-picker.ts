/**
 * Device-grouped channel selection for Live Data (#1671): pure grouping, search and bulk-selection
 * rules. Selection is by stable channel key (`liveChannelKey`); operator-defined names are
 * presentation only and never replace the identity.
 */

import { liveChannelKey, LIVE_SELECTION_LIMIT } from "@/features/live/live-telemetry";
import type { TelemetrySample } from "@/lib/telemetry/types";

export interface PickerChannel {
  key: string;
  /** Operator-defined name when one exists, else the technical channel id. */
  label: string;
  technicalId: string;
  metric: string;
  unit: string;
}

export interface PickerGroup {
  key: string;
  nodeId: string;
  equipmentId: string;
  label: string;
  channels: PickerChannel[];
}

export type ChannelNames = Readonly<Record<string, string>>;

function collator(): Intl.Collator {
  return new Intl.Collator("uk-UA", { numeric: true, sensitivity: "base" });
}

export function groupLiveChannelsByDevice(
  samples: readonly TelemetrySample[],
  names: ChannelNames = {},
): PickerGroup[] {
  const sort = collator();
  const groups = new Map<string, PickerGroup>();
  const seen = new Set<string>();
  for (const sample of samples) {
    const key = liveChannelKey(sample);
    if (seen.has(key)) continue;
    seen.add(key);
    const groupKey = `${sample.node_id}|${sample.equipment_id}`;
    const group = groups.get(groupKey) ?? {
      key: groupKey,
      nodeId: sample.node_id,
      equipmentId: sample.equipment_id,
      label: sample.equipment_id,
      channels: [],
    };
    group.channels.push({
      key,
      label: names[`${sample.node_id}/${sample.channel_id}`] ?? sample.channel_id,
      technicalId: sample.channel_id,
      metric: sample.metric,
      unit: sample.unit,
    });
    groups.set(groupKey, group);
  }
  return [...groups.values()]
    .map((group) => ({
      ...group,
      channels: [...group.channels].sort(
        (left, right) => sort.compare(left.label, right.label) || sort.compare(left.metric, right.metric),
      ),
    }))
    .sort((left, right) => sort.compare(left.label, right.label) || sort.compare(left.nodeId, right.nodeId));
}

/** Case-insensitive match on device, node, channel name/id, metric and unit. A match on the device keeps all its channels. */
export function filterPickerGroups(groups: readonly PickerGroup[], query: string): PickerGroup[] {
  const terms = query.trim().toLocaleLowerCase("uk-UA").split(/\s+/).filter(Boolean);
  if (terms.length === 0) return [...groups];
  const matches = (text: string) => terms.every((term) => text.includes(term));
  return groups.flatMap((group) => {
    const deviceText = `${group.label} ${group.nodeId}`.toLocaleLowerCase("uk-UA");
    if (matches(deviceText)) return [group];
    const channels = group.channels.filter((channel) =>
      matches(
        `${deviceText} ${channel.label} ${channel.technicalId} ${channel.metric} ${channel.unit}`.toLocaleLowerCase(
          "uk-UA",
        ),
      ),
    );
    return channels.length > 0 ? [{ ...group, channels }] : [];
  });
}

export interface SelectionResult {
  selected: string[];
  /** True when some requested channels were not added because of the limit. */
  truncated: boolean;
}

/** Adds the channels in order until the limit; never removes anything and never duplicates. */
export function selectChannels(
  selected: readonly string[],
  keys: readonly string[],
  limit: number = LIVE_SELECTION_LIMIT,
): SelectionResult {
  const next = [...selected];
  let truncated = false;
  for (const key of keys) {
    if (next.includes(key)) continue;
    if (next.length >= limit) {
      truncated = true;
      continue;
    }
    next.push(key);
  }
  return { selected: next, truncated };
}

export function deselectChannels(selected: readonly string[], keys: readonly string[]): string[] {
  const remove = new Set(keys);
  return selected.filter((key) => !remove.has(key));
}

export type GroupState = "none" | "some" | "all";

export function groupSelectionState(
  group: Pick<PickerGroup, "channels">,
  selected: readonly string[],
): GroupState {
  const chosen = group.channels.filter((channel) => selected.includes(channel.key)).length;
  if (chosen === 0) return "none";
  return chosen === group.channels.length ? "all" : "some";
}
