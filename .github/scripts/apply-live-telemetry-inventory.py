from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


write(
    "src/lib/telemetry/dashboard-inventory.ts",
    '''import type { DashboardTelemetryStatus } from "./dashboard-state";
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

function inventoryState(status: DashboardTelemetryStatus, samples: readonly TelemetrySample[]): TelemetryInventoryState {
  if (status === "offline" || status === "error") return "offline";
  if (
    status !== "live" ||
    samples.some((sample) => sample.quality !== "valid" || sample.alarm !== null)
  ) {
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
      validCount: equipmentSamples.filter(
        (sample) => sample.quality === "valid" && sample.alarm === null,
      ).length,
      issueCount: equipmentSamples.filter(
        (sample) => sample.quality !== "valid" || sample.alarm !== null,
      ).length,
      lastCapturedAt: newest(equipmentSamples),
    }))
    .sort((left, right) => left.equipmentId.localeCompare(right.equipmentId));

  const nodes = [...byNode.entries()]
    .map<TelemetryNodeInventory>(([nodeId, nodeSamples]) => ({
      nodeId,
      state: inventoryState(status, nodeSamples),
      equipmentCount: new Set(nodeSamples.map((sample) => sample.equipment_id)).size,
      channelCount: uniqueChannels(nodeSamples),
      validCount: nodeSamples.filter(
        (sample) => sample.quality === "valid" && sample.alarm === null,
      ).length,
      issueCount: nodeSamples.filter(
        (sample) => sample.quality !== "valid" || sample.alarm !== null,
      ).length,
      lastCapturedAt: newest(nodeSamples),
    }))
    .sort((left, right) => left.nodeId.localeCompare(right.nodeId));

  return { nodes, equipment };
}
''',
)

write(
    "src/lib/telemetry/dashboard-inventory.test.ts",
    '''import { describe, expect, it } from "vitest";

import type { TelemetrySample } from "./types";
import { deriveTelemetryInventory } from "./dashboard-inventory";

function sample(
  eventId: string,
  nodeId: string,
  equipmentId: string,
  channelId: string,
  quality: TelemetrySample["quality"] = "valid",
): TelemetrySample {
  return {
    event_id: eventId,
    node_id: nodeId,
    captured_at: `2026-07-26T07:00:0${eventId.at(-1) ?? "0"}Z`,
    metric: "temperature.probe",
    value: quality === "valid" ? 4.2 : null,
    unit: "degC",
    quality,
    source: "test",
    equipment_id: equipmentId,
    channel_id: channelId,
    alarm: null,
    raw_value: null,
    raw_status: null,
  };
}

describe("deriveTelemetryInventory", () => {
  it("groups API records by real nodes, equipment and channels", () => {
    const inventory = deriveTelemetryInventory(
      [
        sample("event-1", "edge-01", "K106", "106-03"),
        sample("event-2", "edge-01", "K106", "106-04", "sensor_error"),
        sample("event-3", "edge-02", "M200", "voltage"),
      ],
      "live",
    );

    expect(inventory.nodes).toEqual([
      expect.objectContaining({
        nodeId: "edge-01",
        state: "warning",
        equipmentCount: 1,
        channelCount: 2,
        validCount: 1,
        issueCount: 1,
      }),
      expect.objectContaining({
        nodeId: "edge-02",
        state: "online",
        equipmentCount: 1,
        channelCount: 1,
      }),
    ]);
    expect(inventory.equipment).toEqual([
      expect.objectContaining({ equipmentId: "K106", nodeId: "edge-01", channelCount: 2 }),
      expect.objectContaining({ equipmentId: "M200", nodeId: "edge-02", channelCount: 1 }),
    ]);
  });

  it("marks all discovered nodes offline when the transport is offline", () => {
    const inventory = deriveTelemetryInventory(
      [sample("event-1", "edge-01", "K106", "106-03")],
      "offline",
    );
    expect(inventory.nodes[0]?.state).toBe("offline");
  });
});
''',
)

write(
    "src/components/dashboard/live-inventory-panel.tsx",
    '''import { AlertTriangle, Boxes, CircleCheck, RadioTower, Server } from "lucide-react";

import type { DashboardTelemetryStatus } from "@/lib/telemetry/dashboard-state";
import { deriveTelemetryInventory } from "@/lib/telemetry/dashboard-inventory";
import type { TelemetrySample } from "@/lib/telemetry/types";

function lastSeen(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("uk-UA", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

const stateClasses = {
  online: "border-emerald-300/15 bg-emerald-400/[0.05] text-emerald-300",
  warning: "border-amber-300/15 bg-amber-400/[0.05] text-amber-300",
  offline: "border-slate-400/10 bg-slate-400/[0.03] text-slate-500",
} as const;

export function LiveInventoryPanel({
  samples,
  status,
}: {
  samples: TelemetrySample[];
  status: DashboardTelemetryStatus;
}) {
  const inventory = deriveTelemetryInventory(samples, status);

  if (inventory.nodes.length === 0) {
    return (
      <div className="grid min-h-44 place-items-center p-5 text-center">
        <div>
          <RadioTower className="mx-auto h-6 w-6 text-slate-600" />
          <p className="mt-3 text-[10px] font-medium text-slate-300">API inventory порожній</p>
          <p className="mt-1 text-[9px] leading-5 text-slate-600">
            Жоден node/equipment/channel record не отримано для поточної організації.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3 p-4 sm:p-5">
      <div className="space-y-2">
        {inventory.nodes.map((node) => (
          <article
            key={node.nodeId}
            className="rounded-2xl border border-white/[0.06] bg-white/[0.018] p-3"
          >
            <div className="flex items-start gap-3">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-white/[0.07] bg-[#071a35] text-cyan-300">
                <Server className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="truncate text-[10px] font-semibold text-white">{node.nodeId}</p>
                  <span
                    className={`rounded-full border px-2 py-1 text-[8px] ${stateClasses[node.state]}`}
                  >
                    {node.state}
                  </span>
                </div>
                <p className="mt-1 text-[9px] text-slate-500">
                  {node.equipmentCount} equipment · {node.channelCount} channels · last {lastSeen(node.lastCapturedAt)}
                </p>
                <div className="mt-2 flex flex-wrap gap-2 text-[8px]">
                  <span className="inline-flex items-center gap-1 text-emerald-300">
                    <CircleCheck className="h-3 w-3" /> {node.validCount} valid
                  </span>
                  <span className={node.issueCount > 0 ? "inline-flex items-center gap-1 text-amber-300" : "text-slate-600"}>
                    <AlertTriangle className="h-3 w-3" /> {node.issueCount} issues
                  </span>
                </div>
              </div>
            </div>
          </article>
        ))}
      </div>

      <div className="border-t border-white/[0.05] pt-3">
        <div className="mb-2 flex items-center gap-2 text-[9px] font-medium text-slate-400">
          <Boxes className="h-3.5 w-3.5" />
          Equipment із latest API
        </div>
        <div className="grid gap-2">
          {inventory.equipment.slice(0, 6).map((equipment) => (
            <div
              key={`${equipment.nodeId}:${equipment.equipmentId}`}
              className="flex items-center justify-between gap-3 rounded-xl border border-white/[0.045] bg-black/10 px-3 py-2"
            >
              <div className="min-w-0">
                <p className="truncate text-[9px] font-medium text-slate-200">{equipment.equipmentId}</p>
                <p className="mt-0.5 truncate text-[8px] text-slate-600">
                  {equipment.nodeId} · {equipment.channelCount} channels
                </p>
              </div>
              <span className={equipment.issueCount > 0 ? "text-[8px] text-amber-300" : "text-[8px] text-emerald-300"}>
                {equipment.issueCount > 0 ? `${equipment.issueCount} issues` : `${equipment.validCount} valid`}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
''',
)

path = "src/hooks/use-dashboard-telemetry.ts"
content = read(path)
content = content.replace(
    '        { node_id: "edge-01" },\n',
    '        {},\n',
    1,
)
content = content.replace(
    '.latest({ node_id: "edge-01", limit: 1000 }, controller.signal)',
    '.latest({ limit: 1000 }, controller.signal)',
    1,
)
content = content.replace(
    '          node_id: "edge-01",\n          metric: "temperature.probe",',
    '          metric: "temperature.probe",',
    1,
)
write(path, content)

path = "src/components/dashboard/dashboard-shell.tsx"
content = read(path)
content = content.replace('import type { EdgeNode } from "@/data/dashboard";\n', "", 1)
content = content.replace('import { NodesPanel } from "./nodes-panel";\n', 'import { LiveInventoryPanel } from "./live-inventory-panel";\nimport { NodesPanel } from "./nodes-panel";\n', 1)
start = content.index("function liveNode(")
end = content.index("function SecurityGate(", start)
content = content[:start] + content[end:]
content = content.replace(
    '''  const nodes =
    telemetry.mode === "live"
      ? [liveNode(telemetry.status, telemetry.view?.freshSamples.length ?? 0)]
      : undefined;
''',
    "",
    1,
)
content = content.replace(
    "                <NodesPanel nodes={nodes} />",
    '''                {telemetry.mode === "live" ? (
                  <LiveInventoryPanel samples={liveSamples} status={telemetry.status} />
                ) : (
                  <NodesPanel />
                )}''',
    1,
)
write(path, content)

path = "src/hooks/use-dashboard-telemetry.test.ts"
content = read(path)
content = content.replace(
    '    expect(firstQuery.node_id).toBe("edge-01");\n',
    '    expect(firstQuery.node_id).toBeUndefined();\n',
    1,
)
content = content.replace(
    '''    await waitFor(() => {
      expect(adapterState.subscribe).toHaveBeenCalledOnce();
    });

    const handlers''',
    '''    await waitFor(() => {
      expect(adapterState.subscribe).toHaveBeenCalledOnce();
    });
    expect(adapterState.latest).toHaveBeenCalledWith(
      { limit: 1000 },
      expect.any(AbortSignal),
    );
    expect(adapterState.subscribe).toHaveBeenCalledWith({}, expect.any(Object));

    const handlers''',
    1,
)
write(path, content)

path = "docs/authenticated-live-telemetry.md"
content = read(path)
marker = "## Authenticated history\n"
section = '''## API-derived inventory\n\nThe production dashboard does not assume a fixed edge node. Latest and WebSocket requests are organization-wide, and node, equipment and channel summaries are grouped from the returned `node_id`, `equipment_id` and `channel_id` fields. Empty inventory is shown explicitly instead of creating a synthetic online node.\n\n'''
if marker not in content:
    raise RuntimeError("Inventory documentation marker was not found")
write(path, content.replace(marker, section + marker, 1))
