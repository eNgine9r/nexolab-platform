"use client";

import { useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Database,
  Gauge,
  LoaderCircle,
  RotateCcw,
  ShieldAlert,
  WifiOff,
  Zap,
} from "lucide-react";

import { EnergyConsumptionPanel } from "@/components/energy/energy-consumption-panel";
import { EnergyHistoryChart } from "@/components/energy/energy-history-chart";
import {
  ENERGY_METERS,
  ENERGY_METRICS,
  energySampleState,
  findEnergySample,
  formatCapturedAt,
  formatEnergyValue,
  resolveEnergyMeter,
  type EnergyMetricId,
  type EnergySampleState,
} from "@/features/energy/energy-telemetry";
import type { EnergyConsumptionLoader } from "@/features/energy/use-energy-consumption";
import type { EnergyHistoryRange, EnergyTelemetryModel } from "@/hooks/use-energy-telemetry";
import type { TelemetrySample } from "@/lib/telemetry/types";

const HISTORY_RANGES: Array<{ value: EnergyHistoryRange; label: string }> = [
  { value: "1h", label: "1 год" },
  { value: "6h", label: "6 год" },
  { value: "24h", label: "24 год" },
  { value: "7d", label: "7 діб" },
];

const OPERATOR_ENERGY_METRICS = ENERGY_METRICS.filter((metric) => metric.id !== "electrical.energy.active");

const STATE_COPY: Record<EnergySampleState, { label: string; className: string }> = {
  live: {
    label: "Live",
    className: "border-emerald-300/20 bg-emerald-400/10 text-emerald-300",
  },
  stale: {
    label: "Застарілі дані",
    className: "border-amber-300/20 bg-amber-400/10 text-amber-200",
  },
  sensor_error: {
    label: "Помилка вимірювання",
    className: "border-red-300/20 bg-red-400/10 text-red-200",
  },
  communication_error: {
    label: "Немає зв’язку",
    className: "border-red-300/20 bg-red-400/10 text-red-200",
  },
  unknown: {
    label: "Невідома якість",
    className: "border-slate-300/15 bg-slate-400/10 text-slate-300",
  },
  empty: {
    label: "Немає даних",
    className: "border-slate-300/10 bg-slate-400/5 text-slate-500",
  },
};

function statusLabel(status: EnergyTelemetryModel["status"]): string {
  switch (status) {
    case "live":
      return "Live";
    case "connecting":
      return "Підключення";
    case "reconnecting":
      return "Відновлення зв’язку";
    case "stale":
      return "Дані застаріли";
    case "offline":
      return "Offline";
    case "unauthorized":
      return "Потрібна авторизація";
    case "forbidden":
      return "Доступ заборонено";
    case "configuration_error":
      return "Помилка конфігурації";
    case "error":
      return "Помилка телеметрії";
    case "demo":
      return "Demo заборонено";
  }
}

function statusTone(status: EnergyTelemetryModel["status"]): string {
  if (status === "live") return "border-emerald-300/20 bg-emerald-400/10 text-emerald-300";
  if (status === "connecting" || status === "reconnecting") {
    return "border-cyan-300/20 bg-cyan-400/10 text-cyan-200";
  }
  if (status === "stale") return "border-amber-300/20 bg-amber-400/10 text-amber-200";
  return "border-red-300/20 bg-red-400/10 text-red-200";
}

function ageCopy(ageMs: number | null): string {
  if (ageMs === null) return "Останній пакет відсутній";
  if (ageMs < 1_000) return "Оновлено щойно";
  if (ageMs < 60_000) return `Оновлено ${Math.round(ageMs / 1_000)} с тому`;
  return `Оновлено ${Math.round(ageMs / 60_000)} хв тому`;
}

function MeterCard({
  unitId,
  selected,
  samples,
  consumption,
  onToggle,
}: {
  unitId: number;
  selected: boolean;
  samples: readonly TelemetrySample[];
  consumption: EnergyConsumptionLoader;
  onToggle: () => void;
}) {
  const meter = ENERGY_METERS.find((item) => item.unitId === unitId)!;
  const power = findEnergySample(samples, unitId, "electrical.power.active");
  const cumulativeEnergy = findEnergySample(samples, unitId, "electrical.energy.active");
  const voltage = findEnergySample(samples, unitId, "electrical.voltage");
  const current = findEnergySample(samples, unitId, "electrical.current");
  const powerFactor = findEnergySample(samples, unitId, "electrical.power_factor");
  const state = energySampleState(power ?? voltage ?? current ?? powerFactor ?? cumulativeEnergy);
  const stateCopy = STATE_COPY[state];

  return (
    <article
      className={`rounded-2xl border p-4 text-left transition ${
        selected
          ? "border-cyan-300/30 bg-cyan-400/[0.07] shadow-[0_16px_40px_rgba(0,198,224,.08)]"
          : "border-white/[0.065] bg-[#091d39]/80 hover:border-white/15"
      }`}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-pressed={selected}
        aria-label={`${selected ? "Виключити" : "Додати"} лічильник ${meter.label} з порівняння`}
        className="block w-full rounded-xl text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[10px] tracking-[0.16em] text-cyan-300 uppercase">KK1 · LE-01MP</p>
            <h2 className="mt-1 text-lg font-semibold text-white">{meter.label}</h2>
            <p className="text-[10px] text-slate-500">Modbus Unit {meter.unitId}</p>
          </div>
          <span className={`rounded-full border px-2.5 py-1 text-[9px] ${stateCopy.className}`}>
            {stateCopy.label}
          </span>
        </div>

        <div className="mt-5">
          <p className="text-[10px] text-slate-500">Активна потужність</p>
          <p className="mt-1 text-3xl font-semibold tracking-tight text-white">{formatEnergyValue(power)}</p>
        </div>
      </button>

      <EnergyConsumptionPanel unitId={unitId} currentCumulative={cumulativeEnergy} loader={consumption} />

      <dl className="mt-4 grid grid-cols-3 gap-2 border-t border-white/[0.06] pt-4">
        <div>
          <dt className="text-[9px] text-slate-600">U</dt>
          <dd className="mt-1 text-[11px] font-medium text-slate-200">{formatEnergyValue(voltage)}</dd>
        </div>
        <div>
          <dt className="text-[9px] text-slate-600">I</dt>
          <dd className="mt-1 text-[11px] font-medium text-slate-200">{formatEnergyValue(current)}</dd>
        </div>
        <div>
          <dt className="text-[9px] text-slate-600">PF</dt>
          <dd className="mt-1 text-[11px] font-medium text-slate-200">{formatEnergyValue(powerFactor)}</dd>
        </div>
      </dl>

      <p className="mt-4 flex items-center gap-1.5 text-[9px] text-slate-600">
        <Clock3 className="h-3 w-3" />
        {formatCapturedAt(power ?? cumulativeEnergy ?? voltage ?? current ?? powerFactor)}
      </p>
    </article>
  );
}

function HistoryPanel({
  telemetry,
  selectedUnitIds,
}: {
  telemetry: EnergyTelemetryModel;
  selectedUnitIds: readonly number[];
}) {
  const definition = ENERGY_METRICS.find((metric) => metric.id === telemetry.selectedMetric)!;
  const hasSelectedHistory = telemetry.historySamples.some((sample) => {
    const meter = resolveEnergyMeter(sample);
    return (
      sample.metric === telemetry.selectedMetric &&
      meter !== null &&
      selectedUnitIds.includes(meter.unitId) &&
      sample.quality === "valid" &&
      sample.value !== null &&
      Number.isFinite(sample.value)
    );
  });

  return (
    <section className="rounded-2xl border border-white/[0.065] bg-[#091d39]/80 p-4 sm:p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-[10px] tracking-[0.16em] text-cyan-300 uppercase">PostgreSQL history</p>
          <h2 className="mt-1 text-lg font-semibold text-white">Порівняння лічильників</h2>
          <p className="mt-1 text-[11px] text-slate-500">
            {definition.label} · {selectedUnitIds.length} вибрано · {telemetry.historySamples.length} записів
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          <label className="grid gap-1 text-[9px] tracking-[0.12em] text-slate-500 uppercase">
            Показник
            <select
              value={telemetry.selectedMetric}
              onChange={(event) => telemetry.setSelectedMetric(event.target.value as EnergyMetricId)}
              className="min-w-56 rounded-xl border border-white/10 bg-[#07182f] px-3 py-2 text-[11px] text-slate-100 outline-none focus:border-cyan-300/40"
            >
              {OPERATOR_ENERGY_METRICS.map((metric) => (
                <option key={metric.id} value={metric.id}>
                  {metric.label}
                </option>
              ))}
            </select>
          </label>
          <div className="flex items-end gap-1" aria-label="Період історії">
            {HISTORY_RANGES.map((range) => (
              <button
                key={range.value}
                type="button"
                onClick={() => telemetry.setHistoryRange(range.value)}
                aria-pressed={telemetry.historyRange === range.value}
                className={`rounded-xl border px-3 py-2 text-[10px] transition ${
                  telemetry.historyRange === range.value
                    ? "border-blue-400/35 bg-blue-500/15 text-blue-200"
                    : "border-white/[0.07] text-slate-500 hover:text-slate-200"
                }`}
              >
                {range.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {telemetry.historyStatus === "loading" ? (
        <div className="grid min-h-64 place-items-center text-center">
          <div>
            <LoaderCircle className="mx-auto h-6 w-6 animate-spin text-cyan-300" />
            <p className="mt-3 text-[11px] text-slate-400">Завантаження історії…</p>
          </div>
        </div>
      ) : telemetry.historyStatus === "error" ? (
        <div className="mt-5 flex min-h-48 flex-col items-center justify-center rounded-2xl border border-amber-300/15 bg-amber-400/[0.035] p-5 text-center">
          <AlertTriangle className="h-6 w-6 text-amber-300" />
          <p className="mt-3 text-sm font-medium text-amber-100">Не вдалося завантажити історію</p>
          <p className="mt-1 max-w-xl text-[11px] text-amber-100/65">
            {telemetry.historyError?.message ?? "Telemetry history API повернув помилку."}
          </p>
          <button
            type="button"
            onClick={telemetry.retryHistory}
            className="mt-4 inline-flex items-center gap-2 rounded-xl border border-amber-300/20 px-3 py-2 text-[10px] text-amber-100"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Повторити
          </button>
        </div>
      ) : !hasSelectedHistory ? (
        <div className="mt-5 grid min-h-48 place-items-center rounded-2xl border border-dashed border-white/[0.08] text-center">
          <div>
            <Database className="mx-auto h-6 w-6 text-slate-600" />
            <p className="mt-3 text-[11px] text-slate-400">Історії для вибраного показника ще немає.</p>
            <p className="mt-1 text-[10px] text-slate-600">
              Це чесний empty state, а не підміна demo-даними.
            </p>
          </div>
        </div>
      ) : (
        <div className="mt-5">
          <EnergyHistoryChart telemetry={telemetry} selectedUnitIds={selectedUnitIds} />
        </div>
      )}
    </section>
  );
}

export function EnergyWorkspace({
  telemetry,
  consumption,
}: {
  telemetry: EnergyTelemetryModel;
  consumption: EnergyConsumptionLoader;
}) {
  const [selectedUnitIds, setSelectedUnitIds] = useState<number[]>(
    ENERGY_METERS.map((meter) => meter.unitId),
  );

  const toggleMeter = (unitId: number) => {
    setSelectedUnitIds((current) => {
      if (current.includes(unitId)) {
        return current.length === 1 ? current : current.filter((item) => item !== unitId);
      }
      return [...current, unitId].sort((left, right) => left - right);
    });
  };

  const validSamples = telemetry.freshSamples.filter(
    (sample) => sample.quality === "valid" && sample.value !== null,
  ).length;
  const problemSamples = telemetry.samples.filter((sample) => sample.quality !== "valid").length;

  return (
    <div className="space-y-4">
      <header className="flex flex-col gap-4 rounded-2xl border border-cyan-300/[0.08] bg-[#091d39]/75 p-4 sm:p-5 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <p className="text-[10px] tracking-[0.18em] text-cyan-300 uppercase">KK1 · Energy telemetry</p>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight text-white">Енергомоніторинг</h1>
            <span className={`rounded-full border px-3 py-1 text-[10px] ${statusTone(telemetry.status)}`}>
              {statusLabel(telemetry.status)}
            </span>
          </div>
          <p className="mt-2 max-w-3xl text-[12px] leading-5 text-slate-400">
            Поточні параметри та споживання за вибраний період для чотирьох LE-01MP. Дані надходять через
            локальні REST, WebSocket і PostgreSQL history без обов’язкової хмари.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-2 rounded-xl border border-white/[0.07] px-3 py-2 text-[10px] text-slate-400">
            <Clock3 className="h-3.5 w-3.5" />
            {ageCopy(telemetry.ageMs)}
          </span>
          <button
            type="button"
            onClick={telemetry.retry}
            aria-label="Повторно підключити енерготелеметрію"
            title="Повторно підключити"
            className="grid h-9 w-9 place-items-center rounded-xl border border-white/[0.08] text-slate-400 transition hover:border-cyan-300/25 hover:text-cyan-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300"
          >
            <RotateCcw className="h-4 w-4" />
          </button>
        </div>
      </header>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Лічильники KK1">
        {ENERGY_METERS.map((meter) => (
          <MeterCard
            key={meter.unitId}
            unitId={meter.unitId}
            selected={selectedUnitIds.includes(meter.unitId)}
            samples={telemetry.samples}
            consumption={consumption}
            onToggle={() => toggleMeter(meter.unitId)}
          />
        ))}
      </section>

      {telemetry.samples.length === 0 ? (
        <section className="rounded-2xl border border-dashed border-white/[0.09] bg-[#091d39]/45 p-8 text-center">
          {telemetry.status === "connecting" || telemetry.status === "reconnecting" ? (
            <LoaderCircle className="mx-auto h-7 w-7 animate-spin text-cyan-300" />
          ) : telemetry.status === "offline" ? (
            <WifiOff className="mx-auto h-7 w-7 text-amber-300" />
          ) : (
            <Gauge className="mx-auto h-7 w-7 text-slate-600" />
          )}
          <h2 className="mt-3 text-sm font-semibold text-white">Дані LE-01MP ще не отримані</h2>
          <p className="mx-auto mt-2 max-w-xl text-[11px] leading-5 text-slate-500">
            Перевірте Device Agent, MQTT і доступ до Telemetry Service. Live mode не підміняється
            демонстраційними значеннями.
          </p>
        </section>
      ) : null}

      <section className="grid gap-3 md:grid-cols-3">
        <article className="rounded-2xl border border-emerald-300/10 bg-emerald-400/[0.035] p-4">
          <div className="flex items-center gap-3">
            <CheckCircle2 className="h-5 w-5 text-emerald-300" />
            <div>
              <p className="text-[10px] text-slate-500">Валідні свіжі серії</p>
              <p className="mt-1 text-xl font-semibold text-white">{validSamples}</p>
            </div>
          </div>
        </article>
        <article className="rounded-2xl border border-amber-300/10 bg-amber-400/[0.035] p-4">
          <div className="flex items-center gap-3">
            <AlertTriangle className="h-5 w-5 text-amber-300" />
            <div>
              <p className="text-[10px] text-slate-500">Проблемні серії</p>
              <p className="mt-1 text-xl font-semibold text-white">{problemSamples}</p>
            </div>
          </div>
        </article>
        <article className="rounded-2xl border border-blue-300/10 bg-blue-400/[0.035] p-4">
          <div className="flex items-center gap-3">
            <Activity className="h-5 w-5 text-blue-300" />
            <div>
              <p className="text-[10px] text-slate-500">Вибрано для порівняння</p>
              <p className="mt-1 text-xl font-semibold text-white">{selectedUnitIds.length} / 4</p>
            </div>
          </div>
        </article>
      </section>

      <HistoryPanel telemetry={telemetry} selectedUnitIds={selectedUnitIds} />

      <section className="grid gap-3 xl:grid-cols-[1fr_360px]">
        <div className="overflow-hidden rounded-2xl border border-white/[0.065] bg-[#091d39]/80">
          <div className="border-b border-white/[0.055] p-4 sm:p-5">
            <p className="text-[10px] tracking-[0.16em] text-cyan-300 uppercase">Latest values</p>
            <h2 className="mt-1 text-lg font-semibold text-white">Підтверджені показники</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-[10px]">
              <thead className="border-b border-white/[0.055] text-slate-500">
                <tr>
                  <th className="px-4 py-3 font-medium">Показник</th>
                  {ENERGY_METERS.map((meter) => (
                    <th key={meter.unitId} className="px-4 py-3 font-medium">
                      {meter.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {OPERATOR_ENERGY_METRICS.map((metric) => (
                  <tr key={metric.id} className="border-b border-white/[0.04] last:border-0">
                    <th className="px-4 py-3 font-medium text-slate-300">
                      <span className="mr-2 text-cyan-300">{metric.shortLabel}</span>
                      {metric.label}
                    </th>
                    {ENERGY_METERS.map((meter) => {
                      const sample = findEnergySample(telemetry.samples, meter.unitId, metric.id);
                      const sampleState = energySampleState(sample);
                      return (
                        <td key={meter.unitId} className="px-4 py-3">
                          <p className="font-medium text-slate-100">{formatEnergyValue(sample)}</p>
                          <p className="mt-1 text-[8px] text-slate-600">{STATE_COPY[sampleState].label}</p>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <aside className="rounded-2xl border border-emerald-300/15 bg-emerald-400/[0.035] p-5">
          <div className="flex items-start gap-3">
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-emerald-300/15 bg-emerald-400/10">
              <ShieldAlert className="h-5 w-5 text-emerald-300" />
            </div>
            <div>
              <p className="text-[10px] tracking-[0.14em] text-emerald-300 uppercase">Evidence status</p>
              <h2 className="mt-1 text-base font-semibold text-white">
                Споживання з підтвердженого лічильника
              </h2>
            </div>
          </div>
          <p className="mt-4 text-[11px] leading-5 text-slate-400">
            Значення `СПОЖИВАННЯ` є різницею двох підтверджених показів `electrical.energy.active` біля меж
            вибраного періоду. Сирий накопичувальний `kWh` залишається незмінним джерелом у телеметрії, але не
            показується як основний операторський KPI.
          </p>
          <div className="mt-4 rounded-xl border border-amber-300/10 bg-amber-400/[0.03] p-3 text-[10px] leading-4 text-amber-100/70">
            Work Package #201 ще очікує окремого погодженого restart/power-cycle доказу для rollover/reset.
            Якщо лічильник зменшується або немає свіжих граничних показів, NEXOLAB показує недоступний стан і
            не вигадує інтервальне споживання.
          </div>
        </aside>
      </section>

      {telemetry.error ? (
        <section className="flex items-start gap-3 rounded-2xl border border-red-300/15 bg-red-400/[0.035] p-4">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-red-300" />
          <div>
            <p className="text-sm font-medium text-red-100">Telemetry connection issue</p>
            <p className="mt-1 text-[11px] leading-5 text-red-100/65">{telemetry.error.message}</p>
          </div>
        </section>
      ) : null}

      <footer className="flex items-center gap-2 px-1 text-[9px] text-slate-600">
        <Zap className="h-3.5 w-3.5" />
        Read-only monitoring · no Modbus write path · local runtime first
      </footer>
    </div>
  );
}
