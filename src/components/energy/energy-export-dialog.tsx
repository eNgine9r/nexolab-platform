"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Download, LoaderCircle, X } from "lucide-react";
import {
  ENERGY_EXPORT_STEPS,
  energyExportSeriesKey,
  type EnergyExportOptions,
  type EnergyExportStatistic,
  type EnergyExportStep,
  type EnergyExportCatalogSeries,
} from "@/features/energy/energy-export-client";
import {
  kyivInput,
  kyivLabel,
  resolveKyivInput,
  selectedKyivTime,
} from "@/features/energy/energy-export-time";
import { ENERGY_METERS } from "@/features/energy/energy-telemetry";
import type { EnergySeriesSelection } from "@/features/energy/energy-series-selection";
import type { EnergyExportController } from "@/features/energy/use-energy-export";

const PERIODS = [
  ["1h", "1 година", 3600],
  ["6h", "6 годин", 21600],
  ["12h", "12 годин", 43200],
  ["24h", "24 години", 86400],
  ["7d", "7 діб", 604800],
  ["custom", "Власний період", 0],
] as const;
const EMPTY_ITEMS: EnergyExportCatalogSeries[] = [];
const STEP_LABELS: Record<EnergyExportStep, string> = {
  0: "RAW · оригінальні вимірювання",
  10: "10 секунд",
  30: "30 секунд",
  60: "1 хвилина",
  300: "5 хвилин",
  600: "10 хвилин",
  900: "15 хвилин",
  1800: "30 хвилин",
  3600: "1 година",
};
const STATISTICS = [
  ["avg", "Середнє"],
  ["min", "Мінімум"],
  ["max", "Максимум"],
] as const;
const fieldClass =
  "mt-2 min-h-11 w-full min-w-0 rounded-xl border border-white/10 bg-[#06142a] px-3 py-2 text-sm text-slate-100 focus-visible:outline-2 focus-visible:outline-cyan-300 disabled:opacity-60";
const buttonClass =
  "min-h-11 rounded-xl border border-white/10 px-3 py-2 text-xs text-slate-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 disabled:opacity-40";
function size(bytes: number | null) {
  if (bytes === null) return "—";
  return bytes < 1_000_000
    ? `${new Intl.NumberFormat("uk-UA", { maximumFractionDigits: 1 }).format(bytes / 1000)} KB`
    : `${new Intl.NumberFormat("uk-UA", { maximumFractionDigits: 1 }).format(bytes / 1_000_000)} MB`;
}

function WallTime({
  label,
  value,
  occurrence,
  onChange,
  onOccurrence,
}: {
  label: string;
  value: string;
  occurrence: string;
  onChange: (value: string) => void;
  onOccurrence: (value: string) => void;
}) {
  const resolved = resolveKyivInput(value);
  return (
    <div className="min-w-0">
      <label className="block text-xs text-slate-300">
        {label}
        <input
          type="datetime-local"
          step="1"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className={fieldClass}
        />
      </label>
      {resolved.kind === "ambiguous" ? (
        <label className="mt-2 block text-xs text-amber-200">
          Цей час повторюється. Оберіть входження
          <select
            aria-label={`${label} · входження часу`}
            value={occurrence}
            onChange={(event) => onOccurrence(event.target.value)}
            className={fieldClass}
          >
            <option value="">Оберіть UTC offset</option>
            {resolved.occurrences.map((item, index) => (
              <option key={item.utc} value={item.utc}>
                {index === 0 ? "Перше" : "Друге"} · UTC{item.offset}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {value && ["invalid", "nonexistent"].includes(resolved.kind) ? (
        <p className="mt-2 text-xs text-amber-200">
          {resolved.kind === "nonexistent"
            ? "Цей час не існує через перехід на літній час."
            : "Перевірте дату й час."}
        </p>
      ) : null}
    </div>
  );
}

export function EnergyExportDialog({
  model,
  defaults,
  onClose,
}: {
  model: EnergyExportController;
  defaults: readonly EnergySeriesSelection[];
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const previewRef = useRef<HTMLElement>(null);
  const initial = model.job?.options;
  const items = model.catalog?.items ?? EMPTY_ITEMS;
  const defaultKeys = useMemo(() => {
    const matching = items.filter((item) =>
      defaults.some(
        (pair) =>
          pair.metric === item.metric &&
          ENERGY_METERS.find((meter) => meter.unitId === pair.unitId)?.equipmentId === item.equipment_id,
      ),
    );
    const fallback = items.filter((item) => item.metric === "electrical.power.active");
    return (matching.length ? matching : fallback.length ? fallback : items.slice(0, 1)).map(
      energyExportSeriesKey,
    );
  }, [items, defaults]);
  const [keys, setKeys] = useState<string[] | null>(() => initial?.series.map(energyExportSeriesKey) ?? null);
  const chosenKeys = keys ?? defaultKeys;
  const [period, setPeriod] = useState<string>(initial ? "custom" : "1h");
  const [fromInput, setFromInput] = useState(() => kyivInput(initial?.from ?? Date.now() - 3600000));
  const [toInput, setToInput] = useState(() => kyivInput(initial?.to ?? Date.now()));
  const [fromOccurrence, setFromOccurrence] = useState(initial ? new Date(initial.from).toISOString() : "");
  const [toOccurrence, setToOccurrence] = useState(initial ? new Date(initial.to).toISOString() : "");
  const [step, setStep] = useState<EnergyExportStep>(initial?.step_seconds ?? 0);
  const [statistics, setStatistics] = useState<EnergyExportStatistic[]>(initial?.statistics ?? ["avg"]);
  const [format, setFormat] = useState<EnergyExportOptions["format"]>(initial?.format ?? "xlsx");
  const [formError, setFormError] = useState<string | null>(null);
  const signature = JSON.stringify([
    [...chosenKeys].sort(),
    period,
    fromInput,
    toInput,
    fromOccurrence,
    toOccurrence,
    step,
    statistics,
    format,
  ]);
  const resolutionSignature = JSON.stringify([
    [...chosenKeys].sort(),
    period,
    fromInput,
    toInput,
    fromOccurrence,
    toOccurrence,
  ]);
  const [binding, setBinding] = useState(initial ? signature : null);
  const [resolutionBinding, setResolutionBinding] = useState(initial ? resolutionSignature : null);
  const job = model.job;
  const jobId = job?.job_id;
  const jobStatus = job?.status;
  useEffect(() => {
    if (jobStatus && ["preview_ready", "ready", "failed", "expired"].includes(jobStatus))
      previewRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [jobId, jobStatus]);
  const locked = Boolean(
    job && job.phase === "render" && ["queued", "running", "ready"].includes(job.status),
  );
  const working = Boolean(job && ["queued", "running"].includes(job.status));
  const selected = items.filter((item) => chosenKeys.includes(energyExportSeriesKey(item)));
  const groups = useMemo(() => {
    const result = new Map<string, typeof items>();
    for (const item of items) {
      const key = JSON.stringify([item.node_id, item.equipment_id]);
      result.set(key, [...(result.get(key) ?? []), item]);
    }
    return [...result.entries()];
  }, [items]);
  const from = selectedKyivTime(fromInput, fromOccurrence);
  const to = selectedKyivTime(toInput, toOccurrence);
  const invalidRange = period === "custom" && (!from || !to || Date.parse(from) >= Date.parse(to));
  const prepared = job?.status === "preview_ready" && binding === signature;
  const available =
    resolutionBinding === resolutionSignature && job?.preview ? job.preview.available_steps : [0];
  const resolutionKnown = resolutionBinding === resolutionSignature && Boolean(job?.preview);
  const toggle = (key: string) =>
    setKeys(chosenKeys.includes(key) ? chosenKeys.filter((item) => item !== key) : [...chosenKeys, key]);
  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  const preview = async () => {
    const end = Date.now();
    if (period === "custom" && to && Date.parse(to) > end + 2000) {
      setFormError("Завершення періоду не може бути в майбутньому.");
      return;
    }
    setFormError(null);
    const preset = PERIODS.find((item) => item[0] === period);
    const options: EnergyExportOptions = {
      series: selected.map(({ node_id, equipment_id, channel_id, metric, unit }) => ({
        node_id,
        equipment_id,
        channel_id,
        metric,
        unit,
      })),
      from: period === "custom" ? from! : new Date(end - (preset?.[2] ?? 3600) * 1000).toISOString(),
      to: period === "custom" ? to! : new Date(end).toISOString(),
      step_seconds: step,
      statistics,
      format,
    };
    setBinding(null);
    if (await model.preview(options)) {
      setBinding(signature);
      setResolutionBinding(resolutionSignature);
    }
  };
  const newExport = async () => {
    if (await model.reset()) {
      setBinding(null);
      setResolutionBinding(null);
      setStep(0);
    }
  };

  return (
    <dialog
      ref={dialogRef}
      aria-modal="true"
      aria-labelledby="energy-export-title"
      className="fixed inset-0 z-[80] m-0 h-full max-h-none w-full max-w-none place-items-center border-0 bg-[#020817]/80 p-3 backdrop-blur-sm open:grid"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onKeyDown={(event) => {
        if (event.key !== "Tab") return;
        const controls = event.currentTarget.querySelectorAll<HTMLElement>(
          "button:not([disabled]), input:not([disabled]), select:not([disabled]), a[href]",
        );
        const first = controls[0],
          last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }}
    >
      <section className="flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-3xl border border-cyan-300/15 bg-[#081a34] text-slate-100 shadow-2xl shadow-black/50">
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-white/[0.06] p-4 sm:p-5">
          <div>
            <h2 id="energy-export-title" className="text-lg font-semibold text-white">
              Експорт історичних даних
            </h2>
            <p className="mt-2 text-xs leading-5 text-slate-400">
              Збережені вимірювання · час Києва (Europe/Kyiv)
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрити експорт"
            className={`${buttonClass} grid shrink-0 place-items-center`}
          >
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="min-h-0 space-y-5 overflow-y-auto p-4 sm:p-5">
          {formError ? (
            <p role="alert" className="text-xs text-amber-200">
              {formError}
            </p>
          ) : null}
          {model.error ? (
            <div
              role="alert"
              className="rounded-xl border border-amber-300/20 bg-amber-400/5 p-3 text-xs text-amber-100"
            >
              <p>{model.error}</p>
              <button
                type="button"
                onClick={() => void (job ? model.refreshJob() : model.refreshCatalog())}
                className={`${buttonClass} mt-3`}
              >
                Повторити перевірку
              </button>
            </div>
          ) : null}
          <fieldset
            disabled={locked || working || model.busy}
            className="min-w-0 space-y-4 disabled:opacity-70"
          >
            <legend className="mb-3 text-sm font-semibold text-white">Лічильники та параметри</legend>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <label className="flex min-h-11 items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-cyan-400"
                  aria-label="Вибрати всі доступні лічильники"
                  checked={
                    groups.length > 0 &&
                    groups.every(([, group]) =>
                      group.some((item) => chosenKeys.includes(energyExportSeriesKey(item))),
                    )
                  }
                  onChange={(event) => {
                    if (!event.target.checked) {
                      setKeys([]);
                      return;
                    }
                    const metrics = new Set(selected.map((item) => item.metric));
                    setKeys(
                      groups.flatMap(([, group]) => {
                        const matching = group.filter(
                          (item) => metrics.size === 0 || metrics.has(item.metric),
                        );
                        return (matching.length ? matching : group.slice(0, 1)).map(energyExportSeriesKey);
                      }),
                    );
                  }}
                />
                Усі доступні лічильники
              </label>
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => setKeys([])} className={buttonClass}>
                  Очистити вибір
                </button>
                <button type="button" onClick={() => void model.refreshCatalog()} className={buttonClass}>
                  Оновити список
                </button>
              </div>
            </div>
            {model.catalogStatus === "loading" || model.catalogStatus === "idle" ? (
              <p role="status" className="flex items-center gap-2 text-xs text-slate-400">
                <LoaderCircle className="h-4 w-4 animate-spin" />
                Завантаження обладнання…
              </p>
            ) : null}
            {model.catalogStatus === "ready" && items.length === 0 ? (
              <p className="rounded-xl border border-dashed border-white/10 p-4 text-sm text-slate-400">
                Доступних збережених параметрів лічильників немає.
              </p>
            ) : null}
            <div className="grid gap-3 sm:grid-cols-2">
              {groups.map(([groupKey, group]) => (
                <fieldset key={groupKey} className="min-w-0 rounded-2xl border border-white/[0.08] p-3">
                  <legend className="max-w-full px-2 text-xs font-semibold text-cyan-200">
                    <label className="flex min-h-10 items-center gap-2">
                      <input
                        type="checkbox"
                        className="h-4 w-4 shrink-0 accent-cyan-400"
                        aria-label={`Експорт лічильника ${group[0].meter_label} · ${group[0].node_id}`}
                        checked={group.some((item) => chosenKeys.includes(energyExportSeriesKey(item)))}
                        onChange={(event) =>
                          setKeys(
                            event.target.checked
                              ? [...new Set([...chosenKeys, ...group.map(energyExportSeriesKey)])]
                              : chosenKeys.filter(
                                  (key) => !group.some((item) => energyExportSeriesKey(item) === key),
                                ),
                          )
                        }
                      />
                      <span className="break-words">
                        {group[0].meter_label} · {group[0].equipment_name}
                      </span>
                    </label>
                  </legend>
                  <div className="space-y-1">
                    {group.map((item) => (
                      <label
                        key={energyExportSeriesKey(item)}
                        className="flex min-h-10 min-w-0 items-start gap-2 rounded-lg px-2 py-2 text-xs text-slate-300"
                      >
                        <input
                          type="checkbox"
                          className="mt-0.5 h-4 w-4 shrink-0 accent-cyan-400"
                          checked={chosenKeys.includes(energyExportSeriesKey(item))}
                          onChange={() => toggle(energyExportSeriesKey(item))}
                          aria-label={`Експорт ${item.meter_label} · ${item.parameter_name} · ${item.node_id} · ${item.channel_id}`}
                        />
                        <span className="min-w-0 break-words">
                          {item.parameter_name} ·{" "}
                          {item.unit === "degC" ? "°C" : item.unit === "ratio" ? "PF" : item.unit}
                          <span className="mt-1 block text-[10px] text-slate-500">{item.channel_id}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                </fieldset>
              ))}
            </div>
            {chosenKeys.length > 64 ? (
              <p className="text-xs text-amber-200">
                Один експорт підтримує до 64 серій. Зменште вибір параметрів.
              </p>
            ) : null}
            <div className="border-t border-white/[0.06] pt-4">
              <p className="text-sm font-semibold text-white">Часовий період</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {PERIODS.map(([value, label]) => (
                  <button
                    type="button"
                    key={value}
                    aria-pressed={period === value}
                    onClick={() => setPeriod(value)}
                    className={`${buttonClass} ${period === value ? "border-cyan-300/30 bg-cyan-400/10 text-cyan-100" : ""}`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              {period === "custom" ? (
                <div className="mt-4 grid min-w-0 gap-4 sm:grid-cols-2">
                  <WallTime
                    label="Початок · Europe/Kyiv"
                    value={fromInput}
                    occurrence={fromOccurrence}
                    onChange={(value) => {
                      setFromInput(value);
                      setFromOccurrence("");
                    }}
                    onOccurrence={setFromOccurrence}
                  />
                  <WallTime
                    label="Завершення · Europe/Kyiv"
                    value={toInput}
                    occurrence={toOccurrence}
                    onChange={(value) => {
                      setToInput(value);
                      setToOccurrence("");
                    }}
                    onOccurrence={setToOccurrence}
                  />
                </div>
              ) : null}
              {invalidRange ? (
                <p className="mt-3 text-xs text-amber-200">
                  Перевірте початок і завершення, оберіть UTC offset для повторного часу. Завершення не може
                  бути в майбутньому.
                </p>
              ) : null}
              <p className="mt-3 text-[11px] text-slate-500">
                Поточний строк зберігання: {model.catalog?.retention_days ?? "—"} діб. Відсутні вимірювання не
                відновлюються.
              </p>
            </div>
            <div className="grid min-w-0 gap-4 border-t border-white/[0.06] pt-4 sm:grid-cols-2">
              <label className="min-w-0 text-xs text-slate-300">
                Крок даних у файлі
                <select
                  aria-label="Крок даних у файлі"
                  value={step}
                  onChange={(event) => setStep(Number(event.target.value) as EnergyExportStep)}
                  className={fieldClass}
                >
                  {ENERGY_EXPORT_STEPS.map((value) => (
                    <option key={value} value={value} disabled={!available.includes(value)}>
                      {STEP_LABELS[value]}
                      {!available.includes(value)
                        ? resolutionKnown
                          ? " · недоступно"
                          : " · після перевірки даних"
                        : ""}
                    </option>
                  ))}
                </select>
                <span className="mt-2 block text-[11px] leading-5 text-slate-500">
                  Доступні кроки визначає попередній перегляд за оригінальною історією. Частота опитування не
                  змінюється.
                </span>
              </label>
              <label className="text-xs text-slate-300">
                Формат
                <select
                  aria-label="Формат"
                  value={format}
                  onChange={(event) => setFormat(event.target.value as EnergyExportOptions["format"])}
                  className={fieldClass}
                >
                  <option value="xlsx">XLSX · Excel і протоколи</option>
                  <option value="csv">CSV · автоматизована обробка</option>
                </select>
              </label>
            </div>
            <fieldset disabled={step === 0} className="min-w-0">
              <legend className="text-xs text-slate-300">Агрегація миттєвих показників</legend>
              <div className="mt-2 flex flex-wrap gap-4">
                {STATISTICS.map(([value, label]) => (
                  <label key={value} className="flex min-h-11 items-center gap-2 text-xs">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-cyan-400"
                      checked={statistics.includes(value)}
                      disabled={statistics.length === 1 && statistics[0] === value}
                      onChange={() =>
                        setStatistics(
                          statistics.includes(value)
                            ? statistics.filter((item) => item !== value)
                            : [...statistics, value],
                        )
                      }
                    />
                    {label}
                  </label>
                ))}
              </div>
              <p className="mt-2 text-[11px] leading-5 text-slate-500">
                Накопичувальні kWh не усереднюються: файл містить кінцевий показ та підтверджену різницю з
                часовими межами.
              </p>
            </fieldset>
          </fieldset>
          {job ? (
            <section
              ref={previewRef}
              className="space-y-3 rounded-2xl border border-cyan-300/15 bg-cyan-400/[0.04] p-4"
              aria-label="Стан експорту"
            >
              <p className="text-sm font-semibold text-white" role="status">
                {job.status === "queued"
                  ? "У черзі"
                  : job.status === "running"
                    ? job.phase === "preview"
                      ? "Підготовка попереднього перегляду…"
                      : "Формування файлу…"
                    : job.status === "preview_ready"
                      ? prepared
                        ? "Попередній перегляд готовий"
                        : "Налаштування змінено · оновіть попередній перегляд"
                      : job.status === "ready"
                        ? "Файл готовий"
                        : job.status === "canceled"
                          ? "Експорт скасовано"
                          : job.status === "expired"
                            ? "Строк зберігання файлу завершився"
                            : "Не вдалося завершити експорт"}
              </p>
              <p className="text-[11px] leading-5 break-words text-slate-400">
                {kyivLabel(job.options.from)} → {kyivLabel(job.options.to)} ·{" "}
                {STEP_LABELS[job.options.step_seconds]} · {job.options.format.toUpperCase()}
              </p>
              {working ? (
                <p aria-live="polite" className="text-xs text-cyan-200">
                  {job.progress.processed.toLocaleString("uk-UA")}{" "}
                  {job.progress.unit === "source_events" ? "вимірювань прочитано" : "рядків записано"}
                  {job.progress.total !== null ? ` з ${job.progress.total.toLocaleString("uk-UA")}` : ""}
                </p>
              ) : null}
              {job.preview ? (
                <>
                  <dl className="grid gap-3 text-xs sm:grid-cols-3">
                    <div>
                      <dt className="text-slate-400">Початкові вимірювання</dt>
                      <dd className="mt-1 text-lg font-semibold text-white">
                        {job.preview.source_events.toLocaleString("uk-UA")}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-slate-400">Рядки у файлі</dt>
                      <dd className="mt-1 text-lg font-semibold text-white">
                        {job.preview.output_rows?.toLocaleString("uk-UA") ?? "—"}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-slate-400">
                        {job.artifact ? "Розмір файлу" : "Орієнтовний розмір"}
                      </dt>
                      <dd className="mt-1 text-lg font-semibold text-white">
                        {job.artifact ? "" : "≈ "}
                        {size(job.artifact?.bytes ?? job.preview.estimated_bytes)}
                      </dd>
                    </div>
                  </dl>
                  {job.preview.source_events === 0 ? (
                    <p className="text-xs text-amber-200">
                      У вибраному періоді даних немає. Змініть період або обладнання.
                    </p>
                  ) : null}
                  <p className="text-[11px] leading-5 text-slate-500">
                    Один рядок може містити кілька одночасних показників. Пропуски та некоректні записи
                    позначаються у файлі.
                  </p>
                  {job.preview.warnings.map((warning) => (
                    <p key={warning} className="text-[11px] leading-5 text-amber-100/80">
                      {warning}
                    </p>
                  ))}
                </>
              ) : null}
              {job.error ? (
                <p role="alert" className="text-xs text-amber-200">
                  {job.error.message}
                </p>
              ) : null}
              <p className="text-[11px] text-slate-500">
                Вікно можна закрити: формування продовжиться у фоні. Збір телеметрії працює далі.
              </p>
            </section>
          ) : null}
        </div>
        <footer className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-white/[0.06] p-4 sm:p-5">
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={onClose} className={buttonClass}>
              Закрити
            </button>
            {job && ["queued", "running", "preview_ready"].includes(job.status) ? (
              <button
                type="button"
                disabled={model.busy}
                onClick={() => void model.cancel()}
                className={buttonClass}
              >
                Скасувати експорт
              </button>
            ) : null}
            {job && ["ready", "failed", "canceled", "expired"].includes(job.status) ? (
              <button
                type="button"
                disabled={model.busy}
                onClick={() => void newExport()}
                className={buttonClass}
              >
                Новий експорт
              </button>
            ) : null}
          </div>
          {job?.status === "ready" ? (
            <button
              type="button"
              disabled={model.busy}
              onClick={() => void model.download()}
              className={`${buttonClass} inline-flex items-center gap-2 border-blue-400/30 bg-blue-500 font-medium text-white`}
            >
              <Download className="h-4 w-4" />
              Завантажити {job.options.format.toUpperCase()}
            </button>
          ) : working ? (
            <span className="inline-flex items-center gap-2 text-xs text-cyan-200">
              <LoaderCircle className="h-4 w-4 animate-spin" />
              {job?.phase === "preview" ? "Перевіряємо дані" : "Готуємо файл"}
            </span>
          ) : prepared ? (
            <button
              type="button"
              disabled={model.busy || job?.preview?.source_events === 0}
              onClick={() => void model.confirm()}
              className={`${buttonClass} border-blue-400/30 bg-blue-500 font-medium text-white`}
            >
              Сформувати {format.toUpperCase()}
            </button>
          ) : (
            <button
              type="button"
              disabled={
                model.busy ||
                model.catalogStatus !== "ready" ||
                selected.length === 0 ||
                selected.length > 64 ||
                invalidRange
              }
              onClick={() => void preview()}
              className={`${buttonClass} border-blue-400/30 bg-blue-500 font-medium text-white`}
            >
              {model.busy ? "Перевірка…" : "Попередній перегляд"}
            </button>
          )}
        </footer>
      </section>
    </dialog>
  );
}
