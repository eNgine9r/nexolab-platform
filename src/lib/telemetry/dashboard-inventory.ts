import type { DashboardTelemetryStatus } from "./dashboard-state";
import type { TelemetrySample } from "./types";

export type TelemetryInventoryState = "online" | "warning" | "offline";

export type TelemetryNodeInventory = {
  nodeId: string;
  state: TelemetryInventoryState;
  equipmentCount: number;
  channelCount: number;
  validCount: number;
  issueCount: number;
  lastCapturedAt: string | null;
};

export type TelemetryEquipmentInventory = {
  equipmentId: string;
  nodeId: string;
  channelCount: number;
  validCount: number;
  issueCount: number;
  lastCapturedAt: string | null;
};

export type TelemetryInventory = {
  nodes: TelemetryNodeInventory[];
  equipment: TelemetryEquipmentInventory[];
};

function newest(samples: readonly TelemetrySample[]): string | null {
  return (
    samples.reduce<string | null>((latest, sample) => {
      if (latest === null || Date.parse(sample.captured_at) > Date.parse(latest)) {
        return sample.captured_at;
      }
      return latest;
    }, null) ?? null
  );
}

function inventoryState(
  status: DashboardTelemetryStatus,
  samples: readonly TelemetrySample[],
): TelemetryInventoryState {
  if (status === "offline" || status === "error") return "offline";
  if (status !== "live" || samples.some((sample) => sample.quality !== "valid" || sample.alarm !== null)) {
    return "warning";
  }
  return "online";
}

function uniqueChannels(samples: readonly TelemetrySample[]): number {
  return new Set(samples.map((sample) => `${sample.equipment_id}:${sample.channel_id}`)).size;
}

export function deriveTelemetryInventory(
  samples: readonly TelemetrySample[],
  status: DashboardTelemetryStatus,
): TelemetryInventory {
  const byNode = new Map<string, TelemetrySample[]>();
  const byEquipment = new Map<string, TelemetrySample[]>();

  for (const sample of samples) {
    const nodeSamples = byNode.get(sample.node_id) ?? [];
    nodeSamples.push(sample);
    byNode.set(sample.node_id, nodeSamples);

    const equipmentKey = `${sample.node_id}:${sample.equipment_id}`;
    const equipmentSamples = byEquipment.get(equipmentKey) ?? [];
    equipmentSamples.push(sample);
    byEquipment.set(equipmentKey, equipmentSamples);
  }

  const equipment = [...byEquipment.values()]
    .map<TelemetryEquipmentInventory>((equipmentSamples) => ({
      equipmentId: equipmentSamples[0]?.equipment_id ?? "unknown-equipment",
      nodeId: equipmentSamples[0]?.node_id ?? "unknown-node",
      channelCount: new Set(equipmentSamples.map((sample) => sample.channel_id)).size,
      validCount: equipmentSamples.filter((sample) => sample.quality === "valid" && sample.alarm === null)
        .length,
      issueCount: equipmentSamples.filter((sample) => sample.quality !== "valid" || sample.alarm !== null)
        .length,
      lastCapturedAt: newest(equipmentSamples),
    }))
    .sort((left, right) => left.equipmentId.localeCompare(right.equipmentId));

  const nodes = [...byNode.entries()]
    .map<TelemetryNodeInventory>(([nodeId, nodeSamples]) => ({
      nodeId,
      state: inventoryState(status, nodeSamples),
      equipmentCount: new Set(nodeSamples.map((sample) => sample.equipment_id)).size,
      channelCount: uniqueChannels(nodeSamples),
      validCount: nodeSamples.filter((sample) => sample.quality === "valid" && sample.alarm === null).length,
      issueCount: nodeSamples.filter((sample) => sample.quality !== "valid" || sample.alarm !== null).length,
      lastCapturedAt: newest(nodeSamples),
    }))
    .sort((left, right) => left.nodeId.localeCompare(right.nodeId));

  return { nodes, equipment };
}
