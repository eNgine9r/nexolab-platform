import { describe, expect, it } from "vitest";

import { liveChannelKey } from "@/features/live/live-telemetry";
import type { TelemetrySample } from "@/lib/telemetry/types";

import {
  buildTelemetryPointHierarchy,
  canonicalizeTelemetryPointSelection,
  collectTelemetryPointBranchIds,
  flattenTelemetryPointHierarchy,
  searchTelemetryPointHierarchy,
  telemetryPointNodeSelectionState,
  telemetryPointSelectionKey,
  toggleTelemetryPointNodeSelection,
  type TelemetryPointBranchNode,
  type TelemetryPointDescriptor,
} from "./hierarchy";

const ORGANIZATION_ID = "org-lab";

function point(
  overrides: Partial<TelemetryPointDescriptor> & Pick<TelemetryPointDescriptor, "channelId" | "metric" | "unit">,
): TelemetryPointDescriptor {
  return {
    organizationId: ORGANIZATION_ID,
    laboratory: { id: "lab-main", label: "Main laboratory" },
    zone: { id: "zone-a", label: "Zone A" },
    equipmentType: { id: "energy-meter", label: "Energy meters" },
    equipment: { id: "LE-01MP", label: "LE-01MP Meter 01" },
    nodeId: "edge-01",
    channelLabel: overrides.channelId,
    metricLabel: overrides.metric,
    ...overrides,
  };
}

function meterPoints(): TelemetryPointDescriptor[] {
  return [
    point({ channelId: "voltage", channelLabel: "Voltage", metric: "voltage", unit: "V" }),
    point({ channelId: "current", channelLabel: "Current", metric: "current", unit: "A" }),
    point({ channelId: "power", channelLabel: "Active power", metric: "active_power", unit: "W" }),
  ];
}

function findBranch(
  hierarchy: ReturnType<typeof buildTelemetryPointHierarchy>,
  kind: TelemetryPointBranchNode["kind"],
  label: string,
): TelemetryPointBranchNode {
  const node = [...hierarchy.nodesById.values()].find(
    (candidate): candidate is TelemetryPointBranchNode =>
      candidate.kind === kind && candidate.label === label,
  );
  if (!node) throw new Error(`Missing ${kind} ${label}`);
  return node;
}

function sampleFor(pointDescriptor: TelemetryPointDescriptor): TelemetrySample {
  return {
    event_id: "event-1",
    node_id: pointDescriptor.nodeId,
    captured_at: "2026-08-15T10:00:00.000Z",
    metric: pointDescriptor.metric,
    value: 230,
    unit: pointDescriptor.unit,
    quality: "valid",
    source: "unit-test",
    equipment_id: pointDescriptor.equipment.id,
    channel_id: pointDescriptor.channelId,
    alarm: null,
    raw_value: 230,
    raw_status: null,
  };
}

describe("TelemetryPointSelector hierarchy", () => {
  it("keeps leaf keys compatible with the canonical Live telemetry identity and organization-scoped", () => {
    const descriptor = meterPoints()[0];
    const otherOrganization = { ...descriptor, organizationId: "org-other" };
    const hierarchy = buildTelemetryPointHierarchy(
      [descriptor, descriptor, otherOrganization],
      ORGANIZATION_ID,
    );

    expect(telemetryPointSelectionKey(descriptor)).toBe(liveChannelKey(sampleFor(descriptor)));
    expect(hierarchy.leafCount).toBe(1);
    expect(hierarchy.deduplicatedPointCount).toBe(1);
    expect(hierarchy.orderedLeafKeys).toEqual([telemetryPointSelectionKey(descriptor)]);
  });

  it("builds a deterministic lab → zone → equipment type → equipment → point hierarchy", () => {
    const points = [
      ...meterPoints(),
      point({
        zone: { id: "zone-b", label: "Zone B" },
        equipmentType: { id: "temperature-controller", label: "Temperature controllers" },
        equipment: { id: "XR170C-106", label: "XR170C Unit 106" },
        channelId: "106-03",
        channelLabel: "Probe 03",
        metric: "temperature.probe",
        metricLabel: "Temperature",
        unit: "degC",
      }),
    ].reverse();

    const hierarchy = buildTelemetryPointHierarchy(points, ORGANIZATION_ID);
    const expanded = new Set(collectTelemetryPointBranchIds(hierarchy));
    const rows = flattenTelemetryPointHierarchy(hierarchy.roots, expanded, { maxVisibleNodes: 100 });

    expect(hierarchy.roots.map((root) => root.label)).toEqual(["Main laboratory"]);
    expect(rows.rows.map((row) => [row.level, row.node.kind, row.node.label])).toEqual([
      [1, "laboratory", "Main laboratory"],
      [2, "zone", "Zone A"],
      [3, "equipment-type", "Energy meters"],
      [4, "equipment", "LE-01MP Meter 01"],
      [5, "point", "Active power · active_power · W"],
      [5, "point", "Current · current · A"],
      [5, "point", "Voltage · voltage · V"],
      [2, "zone", "Zone B"],
      [3, "equipment-type", "Temperature controllers"],
      [4, "equipment", "XR170C Unit 106"],
      [5, "point", "Probe 03 · Temperature · degC"],
    ]);
  });

  it("reports mixed parent state and toggles a parent atomically within a selection limit", () => {
    const hierarchy = buildTelemetryPointHierarchy(meterPoints(), ORGANIZATION_ID);
    const meter = findBranch(hierarchy, "equipment", "LE-01MP Meter 01");
    const first = hierarchy.orderedLeafKeys[0];

    expect(telemetryPointNodeSelectionState(meter, new Set([first]))).toBe("mixed");

    const blocked = toggleTelemetryPointNodeSelection(hierarchy, meter, [first], 2);
    expect(blocked).toEqual({ selected: [first], changed: false, reason: "limit" });

    const selected = toggleTelemetryPointNodeSelection(hierarchy, meter, [], 3);
    expect(selected.reason).toBe("selected");
    expect(selected.selected).toEqual(hierarchy.orderedLeafKeys);
    expect(telemetryPointNodeSelectionState(meter, new Set(selected.selected))).toBe("checked");

    const removed = toggleTelemetryPointNodeSelection(hierarchy, meter, selected.selected, 3);
    expect(removed).toEqual({ selected: [], changed: true, reason: "removed" });
  });

  it("searches in one bounded traversal and preserves canonical selection outside the result set", () => {
    const points = [
      ...meterPoints(),
      ...Array.from({ length: 120 }, (_, index) =>
        point({
          zone: { id: `zone-${index % 6}`, label: `Zone ${index % 6}` },
          equipment: { id: `meter-${index}`, label: `Meter ${index}` },
          channelId: `power-${index}`,
          channelLabel: `Power ${index}`,
          metric: "active_power",
          unit: "W",
        }),
      ),
    ];
    const hierarchy = buildTelemetryPointHierarchy(points, ORGANIZATION_ID);
    const hiddenCommittedKey = telemetryPointSelectionKey(meterPoints()[0]);
    const result = searchTelemetryPointHierarchy(hierarchy, "Meter 119");

    expect(result.visitedNodes).toBeLessThanOrEqual(hierarchy.nodeCount);
    expect(result.matchingLeafKeys).toHaveLength(1);
    expect(result.matchingLeafKeys).not.toContain(hiddenCommittedKey);
    expect(canonicalizeTelemetryPointSelection(hierarchy, [hiddenCommittedKey])).toEqual([
      hiddenCommittedKey,
    ]);
  });

  it("caps visible rendering deterministically without expanding collapsed branches", () => {
    const points = Array.from({ length: 600 }, (_, index) =>
      point({
        zone: { id: `zone-${index % 10}`, label: `Zone ${index % 10}` },
        equipment: { id: `meter-${index}`, label: `Meter ${index}` },
        channelId: `channel-${index}`,
        channelLabel: `Channel ${index}`,
        metric: "active_power",
        unit: "W",
      }),
    );
    const hierarchy = buildTelemetryPointHierarchy(points, ORGANIZATION_ID);
    const expanded = new Set(collectTelemetryPointBranchIds(hierarchy));
    const bounded = flattenTelemetryPointHierarchy(hierarchy.roots, expanded, {
      maxVisibleNodes: 120,
    });
    const collapsed = flattenTelemetryPointHierarchy(hierarchy.roots, new Set(), {
      maxVisibleNodes: 120,
    });

    expect(bounded.rows).toHaveLength(120);
    expect(bounded.truncated).toBe(true);
    expect(collapsed.rows).toHaveLength(1);
    expect(collapsed.truncated).toBe(false);
  });

  it("rejects incomplete descriptors instead of inventing hierarchy metadata", () => {
    const invalid = {
      ...meterPoints()[0],
      laboratory: { id: "", label: "" },
    } satisfies TelemetryPointDescriptor;

    expect(() => buildTelemetryPointHierarchy([invalid], ORGANIZATION_ID)).toThrow(
      "TelemetryPointSelector requires laboratory.id.",
    );
  });
});
