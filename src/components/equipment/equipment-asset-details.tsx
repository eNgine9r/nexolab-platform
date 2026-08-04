"use client";

import Link from "next/link";
import { Cpu, ExternalLink, Gauge, Refrigerator, Thermometer, X } from "lucide-react";

import type { EquipmentRegistryAsset } from "@/features/equipment/asset-registry";

export function EquipmentAssetDetails({
  asset,
  onClose,
}: {
  asset: EquipmentRegistryAsset;
  onClose: () => void;
}) {
  const metadata = detailsFor(asset);
  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-[#020817]/80 p-3 backdrop-blur-sm"
      role="presentation"
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-label={`Паспорт ${asset.primaryIdentifier}`}
        className="max-h-[92vh] w-full max-w-3xl overflow-hidden rounded-3xl border border-cyan-300/15 bg-[#08182e] shadow-2xl shadow-black/50"
      >
        <header className="flex items-start justify-between gap-4 border-b border-white/[0.07] p-5 sm:p-6">
          <div className="flex min-w-0 items-start gap-3">
            <div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl border border-cyan-300/15 bg-cyan-400/10">
              {renderCategoryIcon(asset.category, "h-6 w-6 text-cyan-300")}
            </div>
            <div className="min-w-0">
              <p className="text-[10px] font-semibold tracking-[0.18em] text-cyan-300 uppercase">
                {categoryLabel(asset.category)} · Read-only
              </p>
              <h2 className="mt-1 truncate text-xl font-semibold text-white">{asset.displayName}</h2>
              <p className="mt-1 font-mono text-xs text-slate-400">{asset.primaryIdentifier}</p>
            </div>
          </div>
          <button
            type="button"
            aria-label="Закрити паспорт обладнання"
            title="Закрити"
            onClick={onClose}
            className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-white/10 text-slate-300 hover:bg-white/[0.06] hover:text-white focus:ring-2 focus:ring-cyan-300 focus:outline-none"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="max-h-[calc(92vh-160px)] overflow-y-auto p-5 sm:p-6">
          <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {metadata.map((item) => (
              <div key={item.label} className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-3">
                <dt className="text-[9px] font-semibold tracking-[0.12em] text-slate-500 uppercase">
                  {item.label}
                </dt>
                <dd className="mt-1.5 text-sm break-words text-slate-100">{item.value}</dd>
              </div>
            ))}
          </dl>

          {asset.category === "physical-sensor" ? (
            <section className="mt-5 rounded-2xl border border-amber-300/15 bg-amber-400/[0.07] p-4">
              <h3 className="text-sm font-semibold text-amber-100">Межа metrology contract</h3>
              <p className="mt-2 text-xs leading-5 text-amber-100/75">
                Поточне локальне сховище містить лише статус калібрування. Дата калібрування, наступний
                термін, номер сертифіката, файл документа, лабораторія та невизначеність ще не відстежуються і
                тут не вигадуються.
              </p>
            </section>
          ) : null}
        </div>

        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.07] px-5 py-4 sm:px-6">
          <p className="text-xs text-slate-500">Зміни з цього read-only реєстру не виконуються.</p>
          {asset.canonicalHref ? (
            <Link
              href={asset.canonicalHref}
              className="inline-flex h-10 items-center gap-2 rounded-xl border border-blue-300/15 bg-blue-400/10 px-4 text-xs font-semibold text-blue-100 hover:bg-blue-400/15 focus:ring-2 focus:ring-blue-300 focus:outline-none"
            >
              Відкрити канонічну картку
              <ExternalLink className="h-3.5 w-3.5" />
            </Link>
          ) : (
            <span className="rounded-xl border border-white/[0.07] px-3 py-2 text-xs text-slate-500">
              Редагування для цього типу не реалізоване
            </span>
          )}
        </footer>
      </section>
    </div>
  );
}

function detailsFor(asset: EquipmentRegistryAsset): Array<{ label: string; value: string }> {
  const common = [
    { label: "Категорія", value: categoryLabel(asset.category) },
    { label: "Ідентифікатор", value: asset.primaryIdentifier },
    { label: "Кліматична камера", value: asset.chamberLabel ?? "Не прив’язано" },
    { label: "Розташування", value: asset.locationLabel ?? "Не задано" },
  ];

  if (asset.category === "refrigeration-equipment") {
    const item = asset.source;
    return [
      ...common,
      { label: "Тип", value: item.type },
      { label: "Виробник", value: item.manufacturer },
      { label: "Модель", value: item.model },
      { label: "Серійний номер", value: item.serialNumber },
      { label: "Температурний клас", value: item.temperatureClass },
      { label: "Lifecycle", value: statusLabel(item.lifecycleStatus) },
      { label: "Технічний стан", value: statusLabel(item.status) },
      { label: "Встановлено", value: formatDate(item.installedAt) },
      { label: "Останній сервіс", value: formatDate(item.servicedAt) },
      { label: "Датчики", value: `${item.onlineSensors} онлайн із ${item.totalSensors}` },
      { label: "Активні тривоги", value: String(item.activeAlarms) },
      { label: "Останній зв’язок", value: formatDateTime(item.lastSeenAt) },
      { label: "Версія паспорта", value: `v${item.version}` },
    ];
  }

  if (asset.category === "physical-sensor") {
    const item = asset.source;
    return [
      ...common,
      { label: "Inventory number", value: item.inventoryNumber },
      { label: "Серійний номер", value: item.serialNumber ?? "Не задано" },
      { label: "Позиція сенсора", value: item.sensorPosition },
      { label: "Калібрування", value: calibrationLabel(item.calibrationStatus) },
      { label: "Catalog status", value: statusLabel(item.status) },
      { label: "Канал", value: asset.channel.displayName },
      { label: "Channel id", value: asset.channel.channelId },
      { label: "Source channel", value: asset.channel.sourceChannelId },
      { label: "Параметр", value: `${asset.channel.metricType} · ${asset.channel.unit}` },
      { label: "Контролер", value: asset.controller?.displayName ?? "Не визначено" },
      {
        label: "Підключення контролера",
        value: statusLabel(asset.controller?.connectionStatus ?? "unknown"),
      },
    ];
  }

  const item = asset.source;
  return [
    ...common,
    { label: "Business key", value: item.businessKey },
    { label: "Виробник", value: item.manufacturer },
    { label: "Модель", value: item.model },
    { label: "Modbus unit id", value: String(item.unitId) },
    { label: "Позначення", value: item.designation ?? "Не задано" },
    { label: "Підключення", value: statusLabel(item.connectionStatus) },
    { label: "Catalog status", value: statusLabel(item.status) },
    {
      label: "Вимірювані параметри",
      value:
        item.measuredParameters.length > 0
          ? item.measuredParameters.map((parameter) => `${parameter.metric} · ${parameter.unit}`).join(", ")
          : "Не задано",
    },
  ];
}

export function categoryLabel(category: EquipmentRegistryAsset["category"]): string {
  return {
    "refrigeration-equipment": "Холодильне обладнання",
    "temperature-controller": "Температурний контролер",
    "energy-meter": "Лічильник електроенергії",
    "physical-sensor": "Фізичний датчик",
  }[category];
}

export function calibrationLabel(value: string): string {
  return (
    {
      "not-applicable": "Не застосовується",
      untracked: "Не відстежується",
      current: "Актуальне",
      due: "Наближається термін",
      expired: "Прострочене",
    }[value] ?? value
  );
}

export function statusLabel(value: string): string {
  return (
    {
      active: "Активне",
      inactive: "Неактивне",
      maintenance: "Обслуговування",
      retired: "Виведене",
      normal: "Норма",
      warning: "Попередження",
      alarm: "Тривога",
      offline: "Офлайн",
      connected: "Підключено",
      disconnected: "Відключено",
      unknown: "Невідомо",
    }[value] ?? value
  );
}

function renderCategoryIcon(category: EquipmentRegistryAsset["category"], className: string) {
  switch (category) {
    case "refrigeration-equipment":
      return <Refrigerator className={className} />;
    case "temperature-controller":
      return <Cpu className={className} />;
    case "energy-meter":
      return <Gauge className={className} />;
    case "physical-sensor":
      return <Thermometer className={className} />;
  }
}

function formatDate(value: string): string {
  if (!value) return "Не задано";
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("uk-UA", { dateStyle: "medium" }).format(date);
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("uk-UA", { dateStyle: "medium", timeStyle: "short" }).format(date);
}
