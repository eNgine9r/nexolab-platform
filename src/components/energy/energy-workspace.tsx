"use client";

import { useDisplayTimeZone } from "@/hooks/use-display-time-zone";

import { useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Download,
  Gauge,
  LoaderCircle,
  RotateCcw,
  ShieldAlert,
  WifiOff,
  Zap,
} from "lucide-react";

import { EnergyConsumptionPanel } from "@/components/energy/energy-consumption-panel";
import { EnergyParameterDialog } from "@/components/energy/energy-parameter-dialog";
import { EnergyExportDialog } from "@/components/energy/energy-export-dialog";
import type { EnergyExportController } from "@/features/energy/use-energy-export";
import { EnergyHistoryChart } from "@/components/energy/energy-history-chart";
import {
  ENERGY_METERS,
  ENERGY_METRICS,
  energyMeterSupportsMetric,
  energySampleState,
  findEnergySample,
  formatCapturedAt,
  formatEnergyValue,
  resolveEnergyMeter,
  type EnergySampleState,
} from "@/features/energy/energy-telemetry";
import {
  energySeriesDisplayUnit,
  energySeriesForMeters,
  energySeriesSelectionKey,
  normalizeEnergySeriesSelection,
  type EnergySeriesSelection,
} from "@/features/energy/energy-series-selection";
import type { EnergyConsumptionLoader } from "@/features/energy/use-energy-consumption";
import type { EnergyHistoryRange, EnergyTelemetryModel } from "@/hooks/use-energy-telemetry";
import type { TelemetrySample } from "@/lib/telemetry/types";

const HISTORY_RANGES: Array<{ value: EnergyHistoryRange; label: string }> = [
  { value: "1h", label: "1 год" },
  { value: "6h", label: "6 год" },
  { value: "12h", label: "12 год" },
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

function cadenceAwareEnergySampleState(
  sample: TelemetrySample | null,
  unitId: number,
  cadenceAuthority: EnergyTelemetryModel["cadenceAuthority"],
  now = Date.now(),
): EnergySampleState {
  const capturedAt = sample === null ? Number.NaN : Date.parse(sample.captured_at);
  const staleAfterMs =
    Number.isFinite(capturedAt) && cadenceAuthority !== null
      ? cadenceAuthority.maximumSourceGapMs(unitId, capturedAt, now)
      : null;
  return energySampleState(sample, now, staleAfterMs ?? undefined);
}

function MeterCard({
  unitId,
  selected,
  lastSelected,
  samples,
  cadenceAuthority,
  consumption,
  onToggle,
  onSelectOnly,
}: {
  unitId: number;
  selected: boolean;
  lastSelected: boolean;
  samples: readonly TelemetrySample[];
  cadenceAuthority: EnergyTelemetryModel["cadenceAuthority"];
  consumption: EnergyConsumptionLoader;
  onToggle: () => void;
  onSelectOnly: () => void;
}) {
  const displayTimeZone = useDisplayTimeZone();
  const meter = ENERGY_METERS.find((item) => item.unitId === unitId)!;
  const power = findEnergySample(samples, unitId, "electrical.power.active");
  const cumulativeEnergy = findEnergySample(samples, unitId, "electrical.energy.active");
  const voltage = findEnergySample(samples, unitId, "electrical.voltage");
  const current = findEnergySample(samples, unitId, "electrical.current");
  const powerFactor = findEnergySample(samples, unitId, "electrical.power_factor");
  const state = cadenceAwareEnergySampleState(
    power ?? voltage ?? current ?? powerFactor ?? cumulativeEnergy,
    unitId,
    cadenceAuthority,
  );
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
        disabled={lastSelected}
        aria-describedby={lastSelected ? `energy-meter-${unitId}-selection-note` : undefined}
        aria-pressed={selected}
        aria-label={`${selected ? "Виключити" : "Додати"} лічильник ${meter.label} з порівняння`}
        className="block w-full rounded-xl text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 disabled:cursor-not-allowed"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[10px] tracking-[0.16em] text-cyan-300 uppercase">{meter.modelLabel}</p>
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

      {lastSelected ? (
        <p id={`energy-meter-${unitId}-selection-note`} className="mt-3 text-[10px] leading-4 text-slate-300">
          Для порівняння потрібен хоча б один лічильник. Додайте інший, щоб виключити цей.
        </p>
      ) : null}
      <button
        type="button"
        onClick={onSelectOnly}
        aria-label={`Показати лише лічильник ${meter.label}`}
        className="mt-3 min-h-11 rounded-xl border border-cyan-300/20 px-3 py-2 text-[11px] text-cyan-200 hover:border-cyan-300/40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300"
      >
        Лише цей лічильник
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
        {formatCapturedAt(power ?? cumulativeEnergy ?? voltage ?? current ?? powerFactor, displayTimeZone)}
      </p>
    </article>
  );
}

function HistoryPanel({
  telemetry,
  selectedUnitIds,
  selectedPairs,
  visibilityRevision,
  onApplyPairs,
  onExport,
}: {
  telemetry: EnergyTelemetryModel;
  selectedUnitIds: readonly number[];
  selectedPairs: readonly EnergySeriesSelection[];
  visibilityRevision: number;
  onApplyPairs: (pairs: EnergySeriesSelection[]) => void;
  onExport?: () => void;
}) {
  const [selectorOpen, setSelectorOpen] = useState(false);
  const visiblePairs = selectedPairs.filter((pair) => selectedUnitIds.includes(pair.unitId));
  const validPairKeys = useMemo(() => {
    const keys = new Set<string>();
    for (const sample of telemetry.historySamples) {
      const meter = resolveEnergyMeter(sample);
      if (meter && sample.quality === "valid" && sample.value !== null && Number.isFinite(sample.value)) {
        keys.add(`${meter.unitId}:${sample.metric}`);
      }
    }
    return keys;
  }, [telemetry.historySamples]);
  const missingPairs = visiblePairs.filter((pair) => !validPairKeys.has(energySeriesSelectionKey(pair)));
  const hasSelectedHistory = missingPairs.length < visiblePairs.length;
  const pairLabel = (pair: EnergySeriesSelection) =>
    `${ENERGY_METERS.find((meter) => meter.unitId === pair.unitId)?.label} · ${ENERGY_METRICS.find((metric) => metric.id === pair.metric)?.label}`;

  return (
    <section className="min-w-0 rounded-2xl border border-white/[0.065] bg-[#091d39]/80 p-4 sm:p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <p className="text-[10px] tracking-[0.16em] text-cyan-300 uppercase">Історія вимірювань</p>
          <h2 className="mt-1 text-lg font-semibold text-white">Порівняння лічильників</h2>
          <p className="mt-1 text-[11px] text-slate-500">
            {selectedUnitIds.length} вибрано · {visiblePairs.length} серій · {telemetry.historySamples.length}{" "}
            точок для відображення
          </p>
        </div>
        <div className="flex min-w-0 flex-wrap gap-2">
          {onExport ? (
            <button
              type="button"
              onClick={onExport}
              className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-cyan-300/25 bg-cyan-400/10 px-3 text-xs text-cyan-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300"
            >
              <Download className="h-4 w-4" />
              Експорт даних
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => setSelectorOpen(true)}
            className="min-h-10 rounded-xl border border-cyan-300/25 bg-cyan-400/10 px-3 text-xs text-cyan-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300"
          >
            + Додати параметр
          </button>
          <div className="flex flex-wrap items-end gap-1" aria-label="Період історії">
            {HISTORY_RANGES.map((range) => (
              <button
                key={range.value}
                type="button"
                onClick={() => telemetry.setHistoryRange(range.value)}
                aria-pressed={telemetry.historyRange === range.value}
                className={`min-h-10 rounded-xl border px-3 py-2 text-[10px] transition ${telemetry.historyRange === range.value ? "border-blue-400/35 bg-blue-500/15 text-blue-200" : "border-white/[0.07] text-slate-500 hover:text-slate-200"}`}
              >
                {range.label}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="mt-4 flex flex-wrap gap-2" aria-label="Вибрані параметри графіка">
        {visiblePairs.map((pair) => {
          const metric = ENERGY_METRICS.find((item) => item.id === pair.metric)!;
          const meter = ENERGY_METERS.find((item) => item.unitId === pair.unitId)!;
          return (
            <button
              key={energySeriesSelectionKey(pair)}
              type="button"
              aria-label={`Прибрати ${pairLabel(pair)}`}
              onClick={() =>
                onApplyPairs(
                  selectedPairs.filter(
                    (item) => energySeriesSelectionKey(item) !== energySeriesSelectionKey(pair),
                  ),
                )
              }
              className="min-h-10 max-w-full rounded-xl border border-white/10 px-3 text-xs text-slate-300 focus-visible:outline-2 focus-visible:outline-cyan-300"
            >
              {meter.label} · {metric.shortLabel}, {energySeriesDisplayUnit(pair.metric)}{" "}
              <span aria-hidden="true">×</span>
            </button>
          );
        })}
      </div>
      {telemetry.historyStatus === "loading" ? (
        <p role="status" className="mt-4 flex items-center gap-2 text-xs text-slate-400">
          <LoaderCircle className="h-4 w-4 animate-spin text-cyan-300" />
          Завантаження історії…
        </p>
      ) : null}
      {telemetry.historyError ? (
        <div
          role="alert"
          className="mt-4 rounded-xl border border-amber-300/20 bg-amber-400/[0.04] p-3 text-xs text-amber-100"
        >
          <p>{telemetry.historyError.message}</p>
          <button
            type="button"
            onClick={telemetry.retryHistory}
            className="mt-3 min-h-10 rounded-xl border border-amber-300/20 px-3 text-xs"
          >
            Повторити завантаження історії
          </button>
        </div>
      ) : null}
      {visiblePairs.length === 0 ? (
        <p className="mt-5 rounded-xl border border-dashed border-white/10 p-5 text-sm text-slate-400">
          Додайте параметри для порівняння.
        </p>
      ) : null}
      {visiblePairs.length > 0 &&
      !hasSelectedHistory &&
      telemetry.historyStatus !== "loading" &&
      telemetry.historyStatus !== "error" ? (
        <p className="mt-5 rounded-xl border border-dashed border-white/10 p-5 text-sm text-slate-400">
          Збереженої історії для вибраних параметрів немає.
        </p>
      ) : null}
      {hasSelectedHistory && missingPairs.length > 0 && telemetry.historyStatus !== "loading" ? (
        <p className="mt-3 text-xs text-slate-400">
          Немає валідних вимірювань: {missingPairs.map(pairLabel).join(", ")}.
        </p>
      ) : null}
      {visiblePairs.length > 0 ? (
        <div className={`mt-5 ${hasSelectedHistory ? "" : "hidden"}`}>
          <EnergyHistoryChart
            telemetry={telemetry}
            selectedUnitIds={selectedUnitIds}
            selectedPairs={selectedPairs}
            visibilityRevision={visibilityRevision}
          />
        </div>
      ) : null}
      {selectorOpen ? (
        <EnergyParameterDialog
          selected={selectedPairs}
          onApply={onApplyPairs}
          onClose={() => setSelectorOpen(false)}
        />
      ) : null}
    </section>
  );
}

export function EnergyWorkspace({
  telemetry,
  consumption,
  exporter,
}: {
  telemetry: EnergyTelemetryModel;
  consumption: EnergyConsumptionLoader;
  exporter?: EnergyExportController;
}) {
  const [exportOpen, setExportOpen] = useState(false);
  const openExport = exporter
    ? () => {
        setExportOpen(true);
        void exporter.refreshCatalog();
        if (exporter.job) void exporter.refreshJob();
      }
    : undefined;
  const [selectedUnitIds, setSelectedUnitIds] = useState<number[]>(
    ENERGY_METERS.map((meter) => meter.unitId),
  );

  const [selectedPairs, setSelectedPairs] = useState<EnergySeriesSelection[]>(() =>
    energySeriesForMeters(
      ENERGY_METERS.map((meter) => meter.unitId),
      telemetry.selectedMetrics,
    ),
  );
  const applyPairs = (pairs: EnergySeriesSelection[]) => {
    const next = normalizeEnergySeriesSelection(pairs);
    const previousKeys = new Set(selectedPairs.map(energySeriesSelectionKey));
    setSelectedPairs(next);
    setVisibilityRevision((current) => current + 1);
    telemetry.setSelectedMetrics([...new Set(next.map((pair) => pair.metric))]);
    if (next.length > 0)
      setSelectedUnitIds((current) =>
        ENERGY_METERS.filter(
          (meter) =>
            current.includes(meter.unitId) ||
            next.some(
              (pair) => pair.unitId === meter.unitId && !previousKeys.has(energySeriesSelectionKey(pair)),
            ),
        ).map((meter) => meter.unitId),
      );
  };
  const ensureMeterPairs = (unitId: number) =>
    setSelectedPairs((current) =>
      current.some((pair) => pair.unitId === unitId)
        ? current
        : normalizeEnergySeriesSelection([
            ...current,
            ...energySeriesForMeters([unitId], telemetry.selectedMetrics),
          ]),
    );

  const [visibilityRevision, setVisibilityRevision] = useState(0);

  const toggleMeter = (unitId: number) => {
    if (!selectedUnitIds.includes(unitId)) ensureMeterPairs(unitId);
    setSelectedUnitIds((current) => {
      if (current.includes(unitId)) {
        return current.length === 1 ? current : current.filter((item) => item !== unitId);
      }
      const selected = new Set([...current, unitId]);
      return ENERGY_METERS.filter((meter) => selected.has(meter.unitId)).map((meter) => meter.unitId);
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
            Поточні параметри та споживання за вибраний період для F&F LE-01MP та Eastron SDM120M. Дані
            надходять через локальні REST, WebSocket і PostgreSQL history без обов’язкової хмари.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {openExport ? (
            <button
              type="button"
              onClick={openExport}
              className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-blue-400/30 bg-blue-500 px-4 py-2 text-xs font-medium text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300"
            >
              <Download className="h-4 w-4" />
              Експорт даних
              {exporter?.job && ["queued", "running"].includes(exporter.job.status) ? (
                <span className="text-blue-100">· готується</span>
              ) : exporter?.job?.status === "ready" ? (
                <span className="text-blue-100">· файл готовий</span>
              ) : null}
            </button>
          ) : null}
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

      <section
        className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-5"
        aria-label="Лічильники електроенергії"
      >
        {ENERGY_METERS.map((meter) => (
          <MeterCard
            key={meter.unitId}
            unitId={meter.unitId}
            selected={selectedUnitIds.includes(meter.unitId)}
            lastSelected={selectedUnitIds.length === 1 && selectedUnitIds[0] === meter.unitId}
            samples={telemetry.samples}
            cadenceAuthority={telemetry.cadenceAuthority}
            consumption={consumption}
            onToggle={() => toggleMeter(meter.unitId)}
            onSelectOnly={() => {
              ensureMeterPairs(meter.unitId);
              setSelectedUnitIds([meter.unitId]);
              setVisibilityRevision((current) => current + 1);
            }}
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
          <h2 className="mt-3 text-sm font-semibold text-white">Дані лічильників ще не отримані</h2>
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
              <p className="mt-1 text-xl font-semibold text-white">
                {selectedUnitIds.length} / {ENERGY_METERS.length}
              </p>
            </div>
          </div>
        </article>
      </section>

      <HistoryPanel
        telemetry={telemetry}
        selectedUnitIds={selectedUnitIds}
        visibilityRevision={visibilityRevision}
        selectedPairs={selectedPairs}
        onApplyPairs={applyPairs}
        onExport={openExport}
      />

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
                      if (!energyMeterSupportsMetric(meter, metric.id)) {
                        return (
                          <td key={meter.unitId} className="px-4 py-3">
                            <p className="font-medium text-slate-500">—</p>
                            <p className="mt-1 text-[8px] text-slate-600">Не підтримується</p>
                          </td>
                        );
                      }
                      const sample = findEnergySample(telemetry.samples, meter.unitId, metric.id);
                      const sampleState = cadenceAwareEnergySampleState(
                        sample,
                        meter.unitId,
                        telemetry.cadenceAuthority,
                      );
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
      {exportOpen && exporter ? (
        <EnergyExportDialog
          model={exporter}
          defaults={selectedPairs.filter((pair) => selectedUnitIds.includes(pair.unitId))}
          onClose={() => setExportOpen(false)}
        />
      ) : null}
    </div>
  );
}
