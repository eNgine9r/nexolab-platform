"use client";

import { AlertTriangle, LoaderCircle, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { TelemetryPointSelector } from "@/components/telemetry-selection/telemetry-point-selector";
import { useLiveDashboardInventory } from "@/hooks/use-live-dashboard-inventory";
import {
  buildReportTelemetrySelectionModel,
  reportBindingIdsForSelection,
} from "@/lib/reports/telemetry-selection";
import { createSessionApiClient } from "@/lib/sessions/api-client";
import type { SessionConfiguration } from "@/lib/sessions/types";

export function ReportTelemetrySelector({
  sessionId,
  organizationId,
  onSelectionChange,
}: {
  sessionId: string;
  organizationId: string | null;
  onSelectionChange: (sessionId: string, bindingIds: string[], ready: boolean) => void;
}) {
  const [configuration, setConfiguration] = useState<SessionConfiguration | null>(null);
  const [configurationStatus, setConfigurationStatus] = useState<"idle" | "loading" | "ready" | "error">(
    "idle",
  );
  const [configurationError, setConfigurationError] = useState<Error | null>(null);
  const [selectionState, setSelectionState] = useState<{
    sessionId: string;
    pointKeys: string[];
  } | null>(null);
  const inventory = useLiveDashboardInventory({
    enabled: Boolean(sessionId && organizationId),
    organizationId,
  });

  useEffect(() => {
    if (!sessionId) {
      setConfiguration(null);
      setConfigurationStatus("idle");
      setConfigurationError(null);
      setSelectionState(null);
      return;
    }

    const controller = new AbortController();
    setConfiguration(null);
    setConfigurationStatus("loading");
    setConfigurationError(null);
    setSelectionState(null);
    onSelectionChange(sessionId, [], false);

    void createSessionApiClient()
      .getConfiguration(sessionId, controller.signal)
      .then((value) => {
        if (controller.signal.aborted) return;
        setConfiguration(value);
        setConfigurationStatus("ready");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setConfigurationError(
          error instanceof Error ? error : new Error("Не вдалося завантажити конфігурацію сесії."),
        );
        setConfigurationStatus("error");
        onSelectionChange(sessionId, [], false);
      });

    return () => controller.abort();
  }, [onSelectionChange, sessionId]);

  const model = useMemo(() => {
    if (!configuration || !organizationId) return null;
    return buildReportTelemetrySelectionModel({
      bindings: configuration.bindings,
      inventory: inventory.items,
      organizationId,
    });
  }, [configuration, inventory.items, organizationId]);

  const committedPointKeys =
    model && selectionState?.sessionId === sessionId
      ? selectionState.pointKeys
      : (model?.orderedPointKeys ?? []);

  useEffect(() => {
    if (!model || configurationStatus !== "ready") return;
    if (selectionState?.sessionId === sessionId) return;
    const defaultPointKeys = [...model.orderedPointKeys];
    setSelectionState({ sessionId, pointKeys: defaultPointKeys });
    onSelectionChange(sessionId, reportBindingIdsForSelection(model, defaultPointKeys), true);
  }, [configurationStatus, model, onSelectionChange, selectionState?.sessionId, sessionId]);

  const confirm = (pointKeys: string[]) => {
    if (!model) return;
    setSelectionState({ sessionId, pointKeys });
    onSelectionChange(sessionId, reportBindingIdsForSelection(model, pointKeys), true);
  };

  if (!sessionId) return null;

  if (configurationStatus === "loading" || configurationStatus === "idle") {
    return (
      <div
        className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4"
        data-testid="report-telemetry-selector-loading"
      >
        <div className="flex items-center gap-2 text-[11px] text-slate-400">
          <LoaderCircle className="h-4 w-4 animate-spin text-cyan-300" />
          Читаємо зафіксовані точки телеметрії цієї сесії…
        </div>
      </div>
    );
  }

  if (configurationStatus === "error" || !configuration || !model) {
    return (
      <div
        className="rounded-xl border border-red-300/20 bg-red-400/[0.05] p-4"
        data-testid="report-telemetry-selector-error"
      >
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-300" />
          <div>
            <p className="text-[11px] font-semibold text-red-100">Не вдалося визначити evidence scope</p>
            <p className="mt-1 text-[10px] leading-5 text-red-200/75">
              {configurationError?.message ?? "Конфігурація сесії недоступна."}
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3" data-testid="report-telemetry-selector">
      {inventory.status === "error" ? (
        <div className="flex items-start justify-between gap-3 rounded-xl border border-amber-300/20 bg-amber-400/[0.05] p-3 text-[10px] text-amber-100">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <p>
              Поточний inventory недоступний. Report eligibility не втрачено: показуємо persisted session
              bindings без непідтвердженої taxonomy.
            </p>
          </div>
          <button
            type="button"
            onClick={inventory.retry}
            className="icon-button shrink-0"
            aria-label="Повторити inventory"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>
      ) : null}

      {model.hierarchy.leafCount === 0 ? (
        <div className="rounded-xl border border-amber-300/20 bg-amber-400/[0.05] p-4 text-[11px] text-amber-100">
          У вибраній сесії немає persisted telemetry bindings. Selector-aware report generation недоступна.
        </div>
      ) : (
        <TelemetryPointSelector
          hierarchy={model.hierarchy}
          value={committedPointKeys}
          onConfirm={confirm}
          title="Телеметрія у evidence"
          maxVisibleNodes={800}
        />
      )}

      <p className="text-[10px] leading-5 text-slate-500" data-testid="report-telemetry-selection-count">
        У звіт увійде {committedPointKeys.length} з {model.hierarchy.leafCount} persisted telemetry points.
        Вибір змінює лише immutable report evidence і не впливає на фізичне опитування.
      </p>
    </div>
  );
}
