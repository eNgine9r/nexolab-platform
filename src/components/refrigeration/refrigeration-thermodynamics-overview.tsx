"use client";

import { AlertTriangle, RefreshCw, Snowflake } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import type {
  CircuitThermodynamicsSnapshot,
  DerivedThermodynamicMetric,
  DerivedThermodynamicValue,
  RefrigerationThermodynamicsRepository,
} from "@/features/refrigeration/thermodynamics-repository";

const metricLabels: Record<DerivedThermodynamicMetric, string> = {
  "refrigeration.temperature.evaporation_saturation": "Температура кипіння",
  "refrigeration.temperature.condensation_saturation": "Температура конденсації",
  "refrigeration.superheat": "Перегрів",
  "refrigeration.subcooling": "Переохолодження",
};

const reasonLabels: Record<string, string> = {
  circuit_lifecycle_unresolved: "Стан контуру не визначено.",
  circuit_not_active: "Контур не активний для розрахунку.",
  circuit_configuration_unresolved: "Конфігурація контуру не визначена.",
  calculation_policy_unresolved: "Політика розрахунку не визначена.",
  property_provider_profile_unresolved: "Профіль властивостей холодоагенту не визначено.",
  property_provider_unavailable: "Локальний модуль властивостей недоступний.",
  binding_unresolved: "Не вистачає прив’язки вимірювального сигналу.",
  acquisition_source_unresolved: "Джерело вимірювання не підтверджено.",
  raw_sample_unavailable: "Немає придатного вимірювання для цього часу.",
  instrument_version_unresolved: "Версію вимірювального приладу не визначено.",
};
export function RefrigerationThermodynamicsOverview({
  equipmentId,
  repository,
}: {
  equipmentId: string;
  repository: RefrigerationThermodynamicsRepository | null;
}) {
  const requestVersion = useRef(0);
  const [snapshots, setSnapshots] = useState<CircuitThermodynamicsSnapshot[]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastObservationAt, setLastObservationAt] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!repository) return;
    const version = ++requestVersion.current;
    const observationAt = new Date();
    setLoading(true);
    setError(null);

    try {
      const circuits = await repository.listForEquipment(equipmentId);
      const next = await Promise.all(
        circuits.map((circuit) => repository.readDerived(circuit, observationAt)),
      );
      if (requestVersion.current !== version) return;
      setSnapshots(next);
      setLastObservationAt(observationAt.toISOString());
      setLoaded(true);
    } catch (cause) {
      if (requestVersion.current !== version) return;
      setError(cause instanceof Error ? cause.message : "Не вдалося оновити термодинаміку.");
      setLoaded(true);
    } finally {
      if (requestVersion.current === version) setLoading(false);
    }
  }, [equipmentId, repository]);

  useEffect(() => {
    if (!repository) return;
    const timer = window.setTimeout(() => void refresh(), 0);
    return () => {
      window.clearTimeout(timer);
      requestVersion.current += 1;
    };
  }, [refresh, repository]);

  if (!repository) return null;
  return (
    <section
      className="rounded-2xl border border-white/[0.08] bg-[#081a32] p-4 sm:p-5"
      data-testid="refrigeration-thermodynamics-overview"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-cyan-300/15 bg-cyan-400/[0.06] text-cyan-200">
            <Snowflake className="h-4 w-4" />
          </span>
          <div>
            <p className="text-[10px] tracking-[0.16em] text-cyan-300 uppercase">RFX · Read only</p>
            <h2 className="mt-1 text-lg font-semibold text-white">Термодинаміка контуру</h2>
            <p className="mt-1 text-[10px] text-slate-500">
              Канонічний розрахунок із локального RFX-08B API. Без керування обладнанням.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={loading}
          aria-label="Оновити термодинаміку"
          className="inline-flex min-h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.035] px-3 text-xs text-slate-300 transition hover:border-cyan-300/20 hover:text-white disabled:cursor-wait disabled:opacity-50"
        >
          <RefreshCw className={loading ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} />
          Оновити
        </button>
      </div>

      {error ? (
        <div
          role="alert"
          className="mt-4 flex items-start gap-2 rounded-xl border border-amber-400/20 bg-amber-400/[0.06] p-3 text-xs text-amber-200"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      ) : null}
      {!loaded && loading ? (
        <p className="mt-4 text-xs text-slate-500">Завантаження термодинамічних даних…</p>
      ) : null}

      {loaded && snapshots.length === 0 && !error ? (
        <div className="mt-4 rounded-xl border border-white/[0.07] bg-[#06142a]/70 p-4">
          <p className="text-sm font-medium text-slate-200">Холодильний контур ще не налаштовано</p>
          <p className="mt-1 text-xs text-slate-500">
            Розрахункові значення з’являться тільки після канонічної конфігурації контуру та підтверджених
            джерел вимірювання.
          </p>
        </div>
      ) : null}

      {snapshots.length > 0 ? (
        <div className="mt-4 grid gap-3">
          {snapshots.map((snapshot) => (
            <CircuitPanel key={snapshot.circuit.id} snapshot={snapshot} />
          ))}
        </div>
      ) : null}

      {lastObservationAt ? (
        <p className="mt-3 text-[10px] text-slate-600">
          Час запиту: {formatTimestamp(lastObservationAt)}
          {error ? " · показані останні успішно отримані значення" : ""}
        </p>
      ) : null}
    </section>
  );
}

function CircuitPanel({ snapshot }: { snapshot: CircuitThermodynamicsSnapshot }) {
  return (
    <div className="rounded-xl border border-white/[0.07] bg-[#06142a]/70 p-3 sm:p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-white">{snapshot.circuit.displayName}</p>
          <p className="mt-0.5 text-[10px] text-slate-500">{snapshot.circuit.businessKey}</p>
        </div>
        <span className="text-[10px] text-slate-500">
          Станом на {formatTimestamp(snapshot.observationAt)}
        </span>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {snapshot.metrics.map((metric) => (
          <MetricCard key={metric.metric} metric={metric} />
        ))}
      </div>
    </div>
  );
}

function MetricCard({ metric }: { metric: DerivedThermodynamicValue }) {
  const available =
    metric.availability === "available" && metric.value !== null && Number.isFinite(metric.value);
  const reasonCode = metric.reasonCodes[0] ?? "unavailable";

  return (
    <article className="rounded-xl border border-white/[0.07] bg-[#081a32] p-3">
      <p className="text-[9px] tracking-[0.12em] text-slate-500 uppercase">{metricLabels[metric.metric]}</p>
      <p
        className={
          available
            ? "mt-1 text-xl font-semibold text-white tabular-nums"
            : "mt-1 text-sm font-semibold text-amber-200"
        }
      >
        {available ? `${metric.value!.toFixed(1)} ${metric.unit}` : "Недоступно"}
      </p>
      {available ? (
        <p className="mt-1 text-[10px] text-slate-500">
          Ефективно: {metric.effectiveAt ? formatTimestamp(metric.effectiveAt) : "—"}
        </p>
      ) : (
        <>
          <p className="mt-1 text-[10px] leading-4 text-slate-400">
            {reasonLabels[reasonCode] ?? "Дані не пройшли перевірку якості або повноти."}
          </p>
          <code className="mt-1 block text-[9px] break-all text-slate-600">
            {metric.reasonCodes.length > 0 ? metric.reasonCodes.join(", ") : "unavailable"}
          </code>
        </>
      )}
    </article>
  );
}
function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "—";
  return date.toLocaleString("uk-UA", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
