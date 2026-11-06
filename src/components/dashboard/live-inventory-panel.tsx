"use client";

import { formatOperationalTimestamp } from "@/features/display-time/format";
import { useDisplayTimeZone } from "@/hooks/use-display-time-zone";
import { AlertTriangle, Boxes, CircleCheck, RadioTower, Server } from "lucide-react";

import type { DashboardTelemetryStatus } from "@/lib/telemetry/dashboard-state";
import { deriveTelemetryInventory } from "@/lib/telemetry/dashboard-inventory";
import type { TelemetrySample } from "@/lib/telemetry/types";

function lastSeen(value: string | null, displayTimeZone: string): string {
  if (!value) return "—";
  return formatOperationalTimestamp(new Date(value), displayTimeZone, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

const stateClasses = {
  online: "border-emerald-300/15 bg-emerald-400/[0.05] text-emerald-300",
  warning: "border-amber-300/15 bg-amber-400/[0.05] text-amber-300",
  offline: "border-slate-400/15 bg-slate-400/[0.05] text-slate-300",
} as const;

const stateLabels = {
  online: "Онлайн",
  warning: "Потребує уваги",
  offline: "Офлайн",
} as const;

export function LiveInventoryPanel({
  samples,
  status,
}: {
  samples: TelemetrySample[];
  status: DashboardTelemetryStatus;
}) {
  const displayTimeZone = useDisplayTimeZone();
  const inventory = deriveTelemetryInventory(samples, status);

  if (inventory.nodes.length === 0) {
    return (
      <div className="grid min-h-44 place-items-center p-5 text-center">
        <div>
          <RadioTower className="mx-auto h-6 w-6 text-slate-600" />
          <p className="mt-3 text-xs font-medium text-slate-200">Немає даних про обладнання</p>
          <p className="mt-1 text-xs leading-5 text-slate-400">
            Для вибраної організації API не повернув вузлів, приладів або каналів.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3 p-3 sm:p-4">
      <div className="space-y-2">
        {inventory.nodes.map((node) => (
          <article key={node.nodeId} className="rounded-xl border border-white/[0.06] bg-white/[0.018] p-3">
            <div className="flex items-start gap-2.5">
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-white/[0.07] bg-[#071a35] text-cyan-300">
                <Server className="h-4 w-4" aria-hidden="true" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="min-w-0 text-xs font-semibold break-all text-white">{node.nodeId}</p>
                  <span
                    className={`shrink-0 rounded-full border px-2 py-1 text-[11px] leading-4 font-medium ${stateClasses[node.state]}`}
                  >
                    {stateLabels[node.state]}
                  </span>
                </div>
                <p className="mt-1 text-[11px] leading-4 text-slate-400">
                  {node.equipmentCount} приладів · {node.channelCount} каналів · дані о{" "}
                  {lastSeen(node.lastCapturedAt, displayTimeZone)}
                </p>
                <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] leading-4">
                  <span className="inline-flex items-center gap-1 text-emerald-300">
                    <CircleCheck className="h-3.5 w-3.5" aria-hidden="true" /> {node.validCount} коректних
                  </span>
                  <span
                    className={
                      node.issueCount > 0
                        ? "inline-flex items-center gap-1 text-amber-300"
                        : "inline-flex items-center gap-1 text-slate-400"
                    }
                  >
                    <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" /> {node.issueCount} проблем
                  </span>
                </div>
              </div>
            </div>
          </article>
        ))}
      </div>

      <div className="border-t border-white/[0.05] pt-3">
        <div className="mb-2 flex items-center gap-2 text-xs font-medium text-slate-300">
          <Boxes className="h-3.5 w-3.5" aria-hidden="true" />
          Прилади за останніми даними API
        </div>
        <div className="grid gap-2">
          {inventory.equipment.slice(0, 6).map((equipment) => (
            <div
              key={`${equipment.nodeId}:${equipment.equipmentId}`}
              className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-white/[0.045] bg-black/10 px-3 py-2"
            >
              <div className="min-w-0">
                <p className="text-xs font-medium break-all text-slate-200">{equipment.equipmentId}</p>
                <p className="mt-0.5 text-[11px] leading-4 break-words text-slate-400">
                  {equipment.nodeId} · {equipment.channelCount} каналів
                </p>
              </div>
              <span
                className={
                  equipment.issueCount > 0
                    ? "text-[11px] font-medium text-amber-300"
                    : "text-[11px] font-medium text-emerald-300"
                }
              >
                {equipment.issueCount > 0
                  ? `${equipment.issueCount} проблем`
                  : `${equipment.validCount} коректних`}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
