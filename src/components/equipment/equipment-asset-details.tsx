"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Cpu,
  ExternalLink,
  Gauge,
  MapPin,
  Network,
  Pencil,
  Refrigerator,
  Thermometer,
  X,
} from "lucide-react";

import { EquipmentMetadataEditor } from "@/components/equipment/equipment-metadata-editor";
import type { EquipmentRegistryAsset } from "@/features/equipment/asset-registry";
import type { ClimateCatalogRepository } from "@/features/refrigeration/climate-catalog-repository";
import type { RefrigerationEquipmentRepository } from "@/features/refrigeration/equipment-repository";

export function EquipmentAssetDetails({
  asset,
  canManage,
  equipmentRepository,
  climateCatalogRepository,
  onSaved,
  onClose,
  onPrevious,
  onNext,
  hasPrevious = false,
  hasNext = false,
}: {
  asset: EquipmentRegistryAsset;
  canManage: boolean;
  equipmentRepository: RefrigerationEquipmentRepository | null;
  climateCatalogRepository: ClimateCatalogRepository | null;
  onSaved: () => void;
  onClose: () => void;
  onPrevious?: () => void;
  onNext?: () => void;
  hasPrevious?: boolean;
  hasNext?: boolean;
}) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const sections = useMemo(() => detailsSections(asset), [asset]);
  const [editing, setEditing] = useState(false);
  const [editorDirty, setEditorDirty] = useState(false);
  const [pendingExit, setPendingExit] = useState<"close" | "edit" | null>(null);
  const editable = canEditAsset(asset, canManage, equipmentRepository, climateCatalogRepository);

  const requestClose = useCallback(() => {
    if (editing && editorDirty) {
      setPendingExit("close");
      return;
    }
    onClose();
  }, [editing, editorDirty, onClose]);

  const requestCancelEdit = () => {
    if (editorDirty) {
      setPendingExit("edit");
      return;
    }
    setEditing(false);
  };

  const discardPendingChanges = () => {
    const action = pendingExit;
    setPendingExit(null);
    setEditorDirty(false);
    setEditing(false);
    if (action === "close") onClose();
  };

  useEffect(() => {
    closeButtonRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") requestClose();
      if (!editing && event.key === "ArrowUp" && hasPrevious && onPrevious) onPrevious();
      if (!editing && event.key === "ArrowDown" && hasNext && onNext) onNext();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [editing, hasNext, hasPrevious, onNext, onPrevious, requestClose]);

  return (
    <div className="pointer-events-none fixed inset-0 z-50">
      <button
        type="button"
        aria-label="Закрити інспектор обладнання"
        onClick={requestClose}
        className="pointer-events-auto absolute inset-0 bg-[#020817]/75 backdrop-blur-sm lg:hidden"
      />
      <section
        role="dialog"
        aria-label={`Паспорт ${asset.primaryIdentifier}`}
        className="pointer-events-auto absolute inset-y-0 right-0 flex w-full max-w-[560px] flex-col border-l border-cyan-300/15 bg-[#08182e] shadow-2xl shadow-black/60"
      >
        <header className="border-b border-white/[0.07] p-4 sm:p-5">
          <div className="flex items-start justify-between gap-4">
            <div className="flex min-w-0 items-start gap-3">
              <div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl border border-cyan-300/15 bg-cyan-400/10">
                {renderCategoryIcon(asset.category, "h-6 w-6 text-cyan-300")}
              </div>
              <div className="min-w-0">
                <p className="text-[10px] font-semibold tracking-[0.18em] text-cyan-300 uppercase">
                  {categoryLabel(asset.category)} · {editing ? "Metadata edit" : "Inspector"}
                </p>
                <h2 className="mt-1 truncate text-xl font-semibold text-white">{asset.displayName}</h2>
                <p className="mt-1 font-mono text-xs text-slate-400">{asset.primaryIdentifier}</p>
              </div>
            </div>
            <button
              ref={closeButtonRef}
              type="button"
              aria-label="Закрити паспорт обладнання"
              title="Закрити"
              onClick={requestClose}
              className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-white/10 text-slate-300 hover:bg-white/[0.06] hover:text-white focus:ring-2 focus:ring-cyan-300 focus:outline-none"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="mt-4 flex items-center justify-between gap-3 rounded-xl border border-white/[0.06] bg-white/[0.025] p-2">
            <p className="px-2 text-[10px] text-slate-500">
              {editing
                ? "Під час редагування навігація між активами заблокована"
                : "↑/↓ переходять між сусідніми активами"}
            </p>
            <div className="flex gap-1">
              <button
                type="button"
                aria-label="Попередній актив"
                title="Попередній актив"
                disabled={editing || !hasPrevious}
                onClick={onPrevious}
                className="grid h-8 w-8 place-items-center rounded-lg border border-white/10 text-slate-300 hover:bg-white/[0.06] disabled:cursor-not-allowed disabled:opacity-30"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <button
                type="button"
                aria-label="Наступний актив"
                title="Наступний актив"
                disabled={editing || !hasNext}
                onClick={onNext}
                className="grid h-8 w-8 place-items-center rounded-lg border border-white/10 text-slate-300 hover:bg-white/[0.06] disabled:cursor-not-allowed disabled:opacity-30"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        </header>

        <div className="flex-1 space-y-4 overflow-y-auto p-4 sm:p-5">
          {editing ? (
            <EquipmentMetadataEditor
              asset={asset}
              equipmentRepository={equipmentRepository}
              climateCatalogRepository={climateCatalogRepository}
              onDirtyChange={setEditorDirty}
              onCancel={requestCancelEdit}
              onSaved={() => {
                setEditorDirty(false);
                setEditing(false);
                onSaved();
              }}
            />
          ) : (
            <>
              {sections.map((section) => (
                <section
                  key={section.title}
                  className="rounded-2xl border border-white/[0.07] bg-white/[0.02] p-4"
                >
                  <div className="flex items-center gap-2">
                    <section.icon className="h-4 w-4 text-cyan-300" />
                    <h3 className="text-xs font-semibold tracking-[0.08em] text-slate-200 uppercase">
                      {section.title}
                    </h3>
                  </div>
                  <dl className="mt-3 grid gap-2 sm:grid-cols-2">
                    {section.items.map((item) => (
                      <div
                        key={item.label}
                        className="min-w-0 rounded-xl border border-white/[0.05] bg-[#06142a]/60 p-3"
                      >
                        <dt className="text-[9px] font-semibold tracking-[0.1em] text-slate-500 uppercase">
                          {item.label}
                        </dt>
                        <dd className="mt-1.5 text-sm break-words text-slate-100">{item.value}</dd>
                      </div>
                    ))}
                  </dl>
                </section>
              ))}

              {asset.category === "physical-sensor" ? (
                <section className="rounded-2xl border border-amber-300/15 bg-amber-400/[0.07] p-4">
                  <h3 className="text-sm font-semibold text-amber-100">Межа metrology contract</h3>
                  <p className="mt-2 text-xs leading-5 text-amber-100/75">
                    Поточне локальне сховище містить лише статус калібрування. Дата калібрування, наступний
                    термін, номер сертифіката, файл документа, лабораторія та невизначеність ще не
                    відстежуються і тут не вигадуються.
                  </p>
                </section>
              ) : null}
            </>
          )}

          {pendingExit ? (
            <section role="alert" className="rounded-2xl border border-amber-300/20 bg-amber-400/10 p-4">
              <h3 className="text-sm font-semibold text-amber-100">Є незбережені зміни</h3>
              <p className="mt-1 text-xs leading-5 text-amber-100/70">
                Відкинути локальні зміни редактора? Серверні дані залишаться без змін.
              </p>
              <div className="mt-3 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setPendingExit(null)}
                  className="h-9 rounded-xl border border-white/10 px-3 text-xs text-slate-200"
                >
                  Продовжити редагування
                </button>
                <button
                  type="button"
                  onClick={discardPendingChanges}
                  className="h-9 rounded-xl border border-amber-200/20 bg-amber-300/10 px-3 text-xs font-semibold text-amber-100"
                >
                  Відкинути зміни
                </button>
              </div>
            </section>
          ) : null}
        </div>

        {!editing ? (
          <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.07] px-4 py-4 sm:px-5">
            <p className="text-xs text-slate-500">
              {canManage
                ? "Редагуються лише безпечні адміністративні метадані."
                : "Доступ лише для перегляду."}
            </p>
            <div className="flex flex-wrap gap-2">
              {editable ? (
                <button
                  type="button"
                  onClick={() => {
                    setPendingExit(null);
                    setEditorDirty(false);
                    setEditing(true);
                  }}
                  className="inline-flex h-10 items-center gap-2 rounded-xl bg-blue-500 px-4 text-xs font-semibold text-white hover:bg-blue-400 focus:ring-2 focus:ring-blue-300 focus:outline-none"
                >
                  <Pencil className="h-3.5 w-3.5" />
                  Редагувати метадані
                </button>
              ) : null}
              {asset.canonicalHref ? (
                <Link
                  href={asset.canonicalHref}
                  className="inline-flex h-10 items-center gap-2 rounded-xl border border-blue-300/15 bg-blue-400/10 px-4 text-xs font-semibold text-blue-100 hover:bg-blue-400/15 focus:ring-2 focus:ring-blue-300 focus:outline-none"
                >
                  Канонічна картка
                  <ExternalLink className="h-3.5 w-3.5" />
                </Link>
              ) : null}
            </div>
          </footer>
        ) : null}
      </section>
    </div>
  );
}

function canEditAsset(
  asset: EquipmentRegistryAsset,
  canManage: boolean,
  equipmentRepository: RefrigerationEquipmentRepository | null,
  climateCatalogRepository: ClimateCatalogRepository | null,
): boolean {
  if (!canManage) return false;
  if (asset.category === "refrigeration-equipment") {
    return equipmentRepository !== null && asset.source.lifecycleStatus !== "retired";
  }
  return climateCatalogRepository !== null;
}

type DetailSection = {
  title: string;
  icon: typeof Cpu;
  items: Array<{ label: string; value: string }>;
};

function detailsSections(asset: EquipmentRegistryAsset): DetailSection[] {
  const passport = compactDetails([
    ["Категорія", categoryLabel(asset.category)],
    ["Ідентифікатор", asset.primaryIdentifier],
    ["Виробник", asset.manufacturer],
    ["Модель", asset.model],
    ["Серійний номер", asset.serialNumber],
  ]);
  const placement = compactDetails([
    ["Кліматична камера", asset.chamberLabel],
    ["Розташування", asset.locationLabel],
  ]);
  const connection = compactDetails([
    ["Lifecycle", asset.lifecycleStatus ? statusLabel(asset.lifecycleStatus) : null],
    ["Технічний стан", asset.healthStatus ? statusLabel(asset.healthStatus) : null],
    ["Підключення", asset.connectionStatus ? statusLabel(asset.connectionStatus) : null],
    ["Catalog status", asset.catalogStatus ? statusLabel(asset.catalogStatus) : null],
  ]);

  if (asset.category === "refrigeration-equipment") {
    const item = asset.source;
    passport.push(
      ...compactDetails([
        ["Тип", item.type],
        ["Температурний клас", item.temperatureClass],
        ["Версія паспорта", `v${item.version}`],
      ]),
    );
    connection.push(
      ...compactDetails([
        ["Датчики", `${item.onlineSensors} онлайн із ${item.totalSensors}`],
        ["Активні тривоги", String(item.activeAlarms)],
        ["Останній зв’язок", item.lastSeenAt ? formatDateTime(item.lastSeenAt) : null],
      ]),
    );
    const service = compactDetails([
      ["Встановлено", item.installedAt ? formatDate(item.installedAt) : null],
      ["Останній сервіс", item.servicedAt ? formatDate(item.servicedAt) : null],
    ]);
    return sections([
      ["Паспорт", Cpu, passport],
      ["Підключення і стан", Network, connection],
      ["Розміщення", MapPin, placement],
      ["Сервіс", Gauge, service],
    ]);
  }

  if (asset.category === "physical-sensor") {
    const item = asset.source;
    const metrology = compactDetails([
      ["Inventory number", item.inventoryNumber],
      ["Версія метаданих", `v${item.version}`],
      ["Калібрування", calibrationLabel(item.calibrationStatus)],
      ["Позиція сенсора", item.sensorPosition],
      ["Канал", asset.channel.displayName],
      ["Channel id", asset.channel.channelId],
      ["Source channel", asset.channel.sourceChannelId],
      ["Параметр", `${asset.channel.metricType} · ${asset.channel.unit}`],
    ]);
    const related = compactDetails([
      ["Контролер", asset.controller?.displayName ?? null],
      ["Business key контролера", asset.controller?.businessKey ?? null],
    ]);
    return sections([
      ["Паспорт", Cpu, passport],
      ["Підключення і стан", Network, connection],
      ["Метрологія", Thermometer, metrology],
      ["Розміщення", MapPin, placement],
      ["Пов’язане обладнання", Refrigerator, related],
    ]);
  }

  const item = asset.source;
  passport.push(
    ...compactDetails([
      ["Business key", item.businessKey],
      ["Версія метаданих", `v${item.version}`],
      ["Modbus unit id", String(item.unitId)],
      ["Позначення", item.designation],
    ]),
  );
  const measurements = compactDetails([
    [
      "Вимірювані параметри",
      item.measuredParameters.length > 0
        ? item.measuredParameters.map((parameter) => `${parameter.metric} · ${parameter.unit}`).join(", ")
        : null,
    ],
  ]);
  return sections([
    ["Паспорт", Cpu, passport],
    ["Підключення і стан", Network, connection],
    ["Вимірювання", Gauge, measurements],
    ["Розміщення", MapPin, placement],
  ]);
}

function sections(
  values: Array<[string, typeof Cpu, Array<{ label: string; value: string }>]>,
): DetailSection[] {
  return values
    .filter(([, , items]) => items.length > 0)
    .map(([title, icon, items]) => ({ title, icon, items }));
}

function compactDetails(
  entries: ReadonlyArray<readonly [string, string | null | undefined]>,
): Array<{ label: string; value: string }> {
  return entries
    .filter((entry): entry is readonly [string, string] => Boolean(entry[1]?.trim()))
    .map(([label, value]) => ({ label, value }));
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
