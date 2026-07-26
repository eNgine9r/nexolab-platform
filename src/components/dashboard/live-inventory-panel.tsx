import { AlertTriangle, Boxes, CircleCheck, RadioTower, Server } from "lucide-react";

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
          <article key={node.nodeId} className="rounded-2xl border border-white/[0.06] bg-white/[0.018] p-3">
            <div className="flex items-start gap-3">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-white/[0.07] bg-[#071a35] text-cyan-300">
                <Server className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="truncate text-[10px] font-semibold text-white">{node.nodeId}</p>
                  <span className={`rounded-full border px-2 py-1 text-[8px] ${stateClasses[node.state]}`}>
                    {node.state}
                  </span>
                </div>
                <p className="mt-1 text-[9px] text-slate-500">
                  {node.equipmentCount} equipment · {node.channelCount} channels · last{" "}
                  {lastSeen(node.lastCapturedAt)}
                </p>
                <div className="mt-2 flex flex-wrap gap-2 text-[8px]">
                  <span className="inline-flex items-center gap-1 text-emerald-300">
                    <CircleCheck className="h-3 w-3" /> {node.validCount} valid
                  </span>
                  <span
                    className={
                      node.issueCount > 0 ? "inline-flex items-center gap-1 text-amber-300" : "text-slate-600"
                    }
                  >
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
              <span
                className={
                  equipment.issueCount > 0 ? "text-[8px] text-amber-300" : "text-[8px] text-emerald-300"
                }
              >
                {equipment.issueCount > 0
                  ? `${equipment.issueCount} issues`
                  : `${equipment.validCount} valid`}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
