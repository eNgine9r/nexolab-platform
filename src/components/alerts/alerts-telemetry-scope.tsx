"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

import { TelemetryPointSelector } from "@/components/telemetry-selection/telemetry-point-selector";
import {
  buildAlertTelemetrySelectionModel,
  commitAlertTelemetryScope,
} from "@/lib/alerts/telemetry-selection";
import { useLiveDashboardInventory } from "@/hooks/use-live-dashboard-inventory";

import { AlertsWorkspace } from "./alerts-workspace";

export function AlertsTelemetryScope() {
  const inventory = useLiveDashboardInventory({ enabled: true, organizationId: null });
  const model = useMemo(() => buildAlertTelemetrySelectionModel(inventory.items), [inventory.items]);
  const [telemetryPoints, setTelemetryPoints] = useState<string[] | undefined>(undefined);
  const [committedSelection, setCommittedSelection] = useState<string[] | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const selectorValue = committedSelection ?? model.allPointKeys;

  const selector = (
    <section className="panel p-4 sm:p-5" data-testid="alerts-telemetry-scope">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-[9px] font-semibold tracking-[0.14em] text-cyan-300 uppercase">Telemetry scope</p>
          <h2 className="mt-1 text-base font-semibold text-white">Точки телеметрії для стрічки тривог</h2>
          <p className="mt-1 max-w-3xl text-[11px] leading-5 text-slate-500">
            Вибір звужує production feed на сервері до pagination. Він не змінює правила тривог, polling або
            Modbus.
          </p>
        </div>
        <button type="button" className="secondary-button" onClick={inventory.retry}>
          <RefreshCw className={`h-4 w-4 ${inventory.status === "loading" ? "animate-spin" : ""}`} />
          Оновити inventory
        </button>
      </div>

      {notice ? (
        <p className="mt-3 rounded-xl border border-cyan-300/10 bg-cyan-400/[0.05] px-3 py-2 text-[10px] text-cyan-100" role="status">
          {notice}
        </p>
      ) : null}

      {inventory.status === "loading" || inventory.status === "idle" ? (
        <div className="mt-4 grid min-h-28 place-items-center rounded-2xl border border-white/[0.06] bg-white/[0.02] text-[11px] text-slate-500">
          <span className="inline-flex items-center gap-2">
            <RefreshCw className="h-4 w-4 animate-spin text-cyan-300" />
            Читання canonical inventory…
          </span>
        </div>
      ) : null}

      {inventory.status === "error" ? (
        <div className="mt-4 flex items-start gap-2 rounded-2xl border border-amber-300/15 bg-amber-400/[0.05] p-4 text-[10px] text-amber-100" role="alert">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p className="font-semibold">Canonical inventory недоступний.</p>
            <p className="mt-1 text-amber-100/70">
              {inventory.error?.message ?? "Telemetry selector тимчасово недоступний."} Поточний підтверджений scope стрічки не розширюється автоматично.
            </p>
          </div>
        </div>
      ) : null}

      {inventory.status === "ready" && model.hierarchy.leafCount === 0 ? (
        <div className="mt-4 rounded-2xl border border-dashed border-white/[0.08] p-4 text-center text-[11px] text-slate-500">
          У canonical inventory немає доступних точок. Поточний feed залишається у підтвердженому scope.
        </div>
      ) : null}

      {inventory.status === "ready" && model.hierarchy.leafCount > 0 ? (
        <div className="mt-4">
          <TelemetryPointSelector
            hierarchy={model.hierarchy}
            value={selectorValue}
            title="Точки тривог"
            onConfirm={(selected) => {
              const result = commitAlertTelemetryScope(model.hierarchy, selected);
              if (!result.ok) {
                setNotice(result.message);
                return;
              }
              setTelemetryPoints(result.telemetryPoints);
              setCommittedSelection(result.selectedKeys);
              setNotice(
                result.telemetryPoints === undefined
                  ? "Підтверджено всі доступні точки: серверний feed не звужується."
                  : `Підтверджено ${result.telemetryPoints.length} точок: серверний feed звужено.`,
              );
            }}
            onCancel={() => setNotice("Непідтверджені зміни селектора скасовано.")}
          />
        </div>
      ) : null}
    </section>
  );

  return <AlertsWorkspace telemetryPoints={telemetryPoints} telemetrySelector={selector} />;
}
