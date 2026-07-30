"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  Camera,
  CheckCircle2,
  Cpu,
  ImageIcon,
  Link2,
  Pencil,
  RefreshCw,
  Trash2,
  Wrench,
} from "lucide-react";

import {
  EditEquipmentDialog,
  type EquipmentNodeOption as DialogNodeOption,
} from "@/components/refrigeration/refrigeration-equipment-dialogs";
import type { EquipmentImageMetadata, RefrigerationEquipment } from "@/data/refrigeration";
import type { ClimateCatalogRepository } from "@/features/refrigeration/climate-catalog-repository";
import type {
  EquipmentLifecycleRepository,
  SensorBinding,
} from "@/features/refrigeration/equipment-lifecycle-repository";
import type {
  RefrigerationEquipmentRepository,
  RefrigerationEquipmentUpdateInput,
} from "@/features/refrigeration/equipment-repository";

const lifecycleLabel = {
  active: "Active",
  maintenance: "Maintenance",
  retired: "Retired",
} as const;

const lifecycleTone = {
  active: "border-emerald-400/20 bg-emerald-400/10 text-emerald-200",
  maintenance: "border-amber-400/20 bg-amber-400/10 text-amber-200",
  retired: "border-slate-400/20 bg-slate-400/10 text-slate-300",
} as const;

type Notice = { tone: "success" | "error"; message: string } | null;

export function EquipmentLifecyclePanel({
  equipment,
  repository,
  lifecycleRepository,
  climateCatalogRepository,
  canManage,
  onEquipmentChange,
  onBindingsChanged: _onBindingsChanged,
}: {
  equipment: RefrigerationEquipment;
  repository: RefrigerationEquipmentRepository | null;
  lifecycleRepository: EquipmentLifecycleRepository | null;
  climateCatalogRepository?: ClimateCatalogRepository | null;
  canManage: boolean;
  onEquipmentChange: (equipment: RefrigerationEquipment) => void;
  onBindingsChanged: () => void;
}) {
  const [chambers, setChambers] = useState<DialogNodeOption[]>([]);
  const [images, setImages] = useState<EquipmentImageMetadata[]>([]);
  const [bindings, setBindings] = useState<SensorBinding[]>([]);
  const [loading, setLoading] = useState(
    lifecycleRepository !== null || climateCatalogRepository !== null,
  );
  const [notice, setNotice] = useState<Notice>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [editBusy, setEditBusy] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [retiringImageId, setRetiringImageId] = useState<string | null>(null);

  const mutable = equipment.lifecycleStatus !== "retired";
  const chamberLabel = useMemo(
    () =>
      chambers.find((item) => item.nodeId === equipment.climateChamberId)?.displayName ??
      (equipment.climateChamberId ? "Кліматична камера" : "Не вибрано"),
    [chambers, equipment.climateChamberId],
  );

  const refresh = async () => {
    setLoading(true);
    try {
      const [loadedChambers, loadedImages, loadedBindings] = await Promise.all([
        climateCatalogRepository
          ? climateCatalogRepository.listChambers().then((items) =>
              items.map<DialogNodeOption>((item) => ({
                nodeId: item.id,
                displayName: `${item.name} · ${item.code}`,
                state: item.status,
              })),
            )
          : Promise.resolve([]),
        lifecycleRepository
          ? lifecycleRepository.listImages(equipment.id)
          : Promise.resolve([]),
        lifecycleRepository
          ? lifecycleRepository.listBindings(equipment.id)
          : Promise.resolve([]),
      ]);
      setChambers(loadedChambers);
      setImages(loadedImages);
      setBindings(loadedBindings);
    } catch (error) {
      setNotice({
        tone: "error",
        message: error instanceof Error ? error.message : "Lifecycle-дані не завантажено.",
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
    // Equipment assignment and version are deliberate refresh boundaries.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    equipment.id,
    equipment.climateChamberId,
    equipment.version,
    lifecycleRepository,
    climateCatalogRepository,
  ]);

  const savePassport = async (input: RefrigerationEquipmentUpdateInput) => {
    if (!repository) return;
    setEditBusy(true);
    setEditError(null);
    try {
      const updated = await repository.update(equipment.id, input, equipment.version);
      onEquipmentChange(updated);
      setEditOpen(false);
      setNotice({ tone: "success", message: "Паспорт обладнання оновлено." });
    } catch (error) {
      setEditError(error instanceof Error ? error.message : "Паспорт не оновлено.");
    } finally {
      setEditBusy(false);
    }
  };

  const retireImage = async (image: EquipmentImageMetadata) => {
    if (!lifecycleRepository) return;
    setRetiringImageId(image.id);
    setNotice(null);
    try {
      await lifecycleRepository.retireImage(equipment.id, image.id, equipment.version);
      onEquipmentChange({ ...equipment, version: equipment.version + 1 });
      setNotice({ tone: "success", message: `${image.fileName} переміщено до історії.` });
    } catch (error) {
      setNotice({
        tone: "error",
        message: error instanceof Error ? error.message : "Фото не переміщено до історії.",
      });
    } finally {
      setRetiringImageId(null);
    }
  };

  return (
    <section
      className="mb-3 rounded-2xl border border-white/[0.07] bg-[#08182e]/90 p-3"
      aria-label="Lifecycle обладнання"
    >
      <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`rounded-full border px-2.5 py-1 text-[10px] ${lifecycleTone[equipment.lifecycleStatus]}`}
          >
            {lifecycleLabel[equipment.lifecycleStatus]}
          </span>
          <span className="text-[11px] text-slate-500">
            Паспорт v{equipment.version} · {equipment.laboratory ?? "Лабораторію не задано"}
            {equipment.zone ? ` · ${equipment.zone}` : ""}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <IconButton
            label="Оновити lifecycle-дані"
            onClick={() => void refresh()}
            disabled={loading}
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </IconButton>
          {canManage && repository && mutable ? (
            <IconButton
              label="Редагувати паспорт обладнання"
              onClick={() => {
                setEditError(null);
                setEditOpen(true);
              }}
              accent
            >
              <Pencil className="h-4 w-4" />
            </IconButton>
          ) : null}
        </div>
      </div>

      {notice ? (
        <div
          role={notice.tone === "error" ? "alert" : "status"}
          className={`mb-3 flex items-center gap-2 rounded-xl border px-3 py-2 text-xs ${
            notice.tone === "success"
              ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-200"
              : "border-rose-400/20 bg-rose-400/10 text-rose-200"
          }`}
        >
          {notice.tone === "success" ? (
            <CheckCircle2 className="h-4 w-4" />
          ) : (
            <AlertCircle className="h-4 w-4" />
          )}
          {notice.message}
        </div>
      ) : null}

      {equipment.lifecycleStatus === "retired" ? (
        <div className="mb-3 flex items-start gap-2 rounded-xl border border-slate-400/15 bg-slate-400/[0.06] p-3 text-xs text-slate-300">
          <Wrench className="mt-0.5 h-4 w-4 shrink-0" />
          Обладнання виведено з експлуатації. Паспорт, фото, bindings і схема доступні
          лише для аудиту.
        </div>
      ) : null}

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.4fr)]">
        <LifecycleCard icon={Cpu} title="Структуроване розташування">
          <InfoRow label="Лабораторія" value={equipment.laboratory ?? "Не задано"} />
          <InfoRow label="Зона" value={equipment.zone ?? "Не задано"} />
          <InfoRow label="Камера" value={chamberLabel} />
          <InfoRow label="Джерело даних" value={equipment.transportNodeId ?? "Не визначено"} />
          <InfoRow label="Lifecycle" value={lifecycleLabel[equipment.lifecycleStatus]} />
        </LifecycleCard>

        <LifecycleCard icon={Camera} title="Історія фотографій">
          {images.length ? (
            <div className="space-y-2">
              {images.slice(0, 4).map((image) => (
                <div
                  key={image.id}
                  className="flex items-center gap-2 rounded-xl border border-white/[0.06] p-2"
                >
                  {image.sourceUrl ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={image.sourceUrl}
                      alt={image.alt}
                      className="h-10 w-14 rounded-lg object-cover"
                    />
                  ) : (
                    <div className="grid h-10 w-14 place-items-center rounded-lg bg-white/[0.04]">
                      <ImageIcon className="h-4 w-4 text-slate-500" />
                    </div>
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[11px] text-slate-200">{image.fileName}</p>
                    <p className="text-[9px] text-slate-600">
                      {image.retiredAt ? "Історичне" : `${image.widthPx}×${image.heightPx}`}
                    </p>
                  </div>
                  {canManage && mutable && !image.retiredAt ? (
                    <IconButton
                      label={`Перемістити ${image.fileName} до історії`}
                      tone="danger"
                      compact
                      disabled={retiringImageId === image.id}
                      onClick={() => void retireImage(image)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </IconButton>
                  ) : null}
                </div>
              ))}
            </div>
          ) : (
            <EmptyState text="Фото з’являться після першого завантаження у редакторі схеми." />
          )}
        </LifecycleCard>

        <LifecycleCard icon={Link2} title={`Sensor bindings · ${bindings.length}`}>
          {bindings.length ? (
            <div className="max-h-52 space-y-2 overflow-y-auto pr-1">
              {bindings.map((binding) => (
                <div
                  key={binding.id}
                  className="flex items-center gap-2 rounded-xl border border-white/[0.06] p-2"
                >
                  <div className="grid h-8 w-8 place-items-center rounded-lg border border-cyan-300/15 bg-cyan-300/[0.06] text-cyan-200">
                    <Link2 className="h-3.5 w-3.5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[11px] font-medium text-slate-200">
                      {binding.label} · {binding.channelId}
                    </p>
                    <p className="text-[9px] text-slate-600">
                      {binding.slotKey} · полиця {binding.shelf} · позиція {binding.position}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState text="Активних bindings немає." />
          )}
          <p className="mt-3 rounded-xl border border-cyan-300/10 bg-cyan-300/[0.035] px-3 py-2 text-[10px] leading-relaxed text-slate-500">
            Додавання, заміна та видалення датчиків виконуються на підкладці в режимі
            редагування. Усі зміни зберігаються одним атомарним пакетом.
          </p>
        </LifecycleCard>
      </div>

      <EditEquipmentDialog
        equipment={editOpen ? equipment : null}
        busy={editBusy}
        error={editError}
        nodeOptions={chambers}
        onClose={() => {
          if (!editBusy) setEditOpen(false);
        }}
        onSubmit={savePassport}
      />
    </section>
  );
}

function LifecycleCard({
  icon: Icon,
  title,
  children,
}: {
  icon: typeof Cpu;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
      <div className="mb-3 flex items-center gap-2">
        <Icon className="h-4 w-4 text-cyan-300" />
        <h3 className="text-xs font-semibold text-slate-200">{title}</h3>
      </div>
      {children}
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-white/[0.05] py-2 last:border-0">
      <span className="text-[10px] text-slate-600">{label}</span>
      <span className="truncate text-right text-[11px] text-slate-300">{value}</span>
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <p className="rounded-xl border border-dashed border-white/[0.08] p-4 text-center text-[10px] text-slate-600">
      {text}
    </p>
  );
}

function IconButton({
  label,
  children,
  onClick,
  disabled = false,
  accent = false,
  compact = false,
  tone = "default",
}: {
  label: string;
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  accent?: boolean;
  compact?: boolean;
  tone?: "default" | "danger";
}) {
  const toneClass = accent
    ? "border-cyan-300/25 bg-cyan-400/15 text-cyan-100 hover:bg-cyan-400/20"
    : tone === "danger"
      ? "border-rose-400/15 bg-rose-400/[0.06] text-rose-300 hover:bg-rose-400/12"
      : "border-white/10 bg-white/[0.035] text-slate-400 hover:text-white";
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className={`grid place-items-center rounded-xl border transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 disabled:cursor-not-allowed disabled:opacity-35 ${compact ? "h-8 w-8" : "h-10 w-10"} ${toneClass}`}
    >
      {children}
    </button>
  );
}
