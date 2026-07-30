"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import {
  AlertTriangle,
  CopyPlus,
  LoaderCircle,
  Pencil,
  Plus,
  RadioTower,
  Trash2,
  X,
} from "lucide-react";

import { RefrigerationIconButton } from "@/components/refrigeration/refrigeration-icon-button";
import type { EquipmentLifecycleStatus, RefrigerationEquipment } from "@/data/refrigeration";
import type {
  RefrigerationEquipmentCreateInput,
  RefrigerationEquipmentUpdateInput,
} from "@/features/refrigeration/equipment-repository";

export type EquipmentNodeOption = {
  nodeId: string;
  displayName: string;
  state: string;
};

export type ClimateChamberEquipmentSummary = {
  temperatureControllers: number;
  temperatureChannels: number;
  energyMeters: number;
  energyMeterEmptyMessage: string | null;
};

type PassportDialogMode = "create" | "duplicate" | "edit";
type ChamberLoadState = "idle" | "loading" | "ready" | "error";

const initialForm: RefrigerationEquipmentCreateInput = {
  code: "",
  name: "",
  location: "",
  laboratory: "",
  zone: "",
  nodeId: "",
  type: "Холодильна вітрина",
  manufacturer: "",
  model: "",
  serialNumber: "",
  temperatureClass: "",
  installedAt: "",
  servicedAt: "",
  lifecycleStatus: "active",
  totalSensors: 0,
};

export function CreateEquipmentDialog({
  open,
  busy,
  error,
  nodeOptions = [],
  initialValue,
  intent = "create",
  onClose,
  onSubmit,
  onClimateChamberChange,
}: {
  open: boolean;
  busy: boolean;
  error: string | null;
  nodeOptions?: EquipmentNodeOption[];
  initialValue?: RefrigerationEquipmentCreateInput | null;
  intent?: "create" | "duplicate";
  onClose: () => void;
  onSubmit: (input: RefrigerationEquipmentCreateInput) => Promise<void>;
  onClimateChamberChange?: (
    nodeId: string,
  ) => Promise<ClimateChamberEquipmentSummary>;
}) {
  return (
    <EquipmentPassportDialog
      mode={intent}
      open={open}
      busy={busy}
      error={error}
      initialValue={initialValue ?? initialForm}
      nodeOptions={nodeOptions}
      onClose={onClose}
      onSubmit={onSubmit}
      onClimateChamberChange={onClimateChamberChange}
    />
  );
}

export function EditEquipmentDialog({
  equipment,
  busy,
  error,
  nodeOptions,
  onClose,
  onSubmit,
  onClimateChamberChange,
}: {
  equipment: RefrigerationEquipment | null;
  busy: boolean;
  error: string | null;
  nodeOptions: EquipmentNodeOption[];
  onClose: () => void;
  onSubmit: (input: RefrigerationEquipmentUpdateInput) => Promise<void>;
  onClimateChamberChange?: (
    nodeId: string,
  ) => Promise<ClimateChamberEquipmentSummary>;
}) {
  if (!equipment) return null;
  return (
    <EquipmentPassportDialog
      mode="edit"
      open
      busy={busy}
      error={error}
      initialValue={equipmentToInput(equipment)}
      nodeOptions={nodeOptions}
      onClose={onClose}
      onSubmit={onSubmit}
      onClimateChamberChange={onClimateChamberChange}
    />
  );
}

function EquipmentPassportDialog({
  mode,
  open,
  busy,
  error,
  initialValue,
  nodeOptions,
  onClose,
  onSubmit,
  onClimateChamberChange,
}: {
  mode: PassportDialogMode;
  open: boolean;
  busy: boolean;
  error: string | null;
  initialValue: RefrigerationEquipmentCreateInput;
  nodeOptions: EquipmentNodeOption[];
  onClose: () => void;
  onSubmit: (input: RefrigerationEquipmentCreateInput) => Promise<void>;
  onClimateChamberChange?: (
    nodeId: string,
  ) => Promise<ClimateChamberEquipmentSummary>;
}) {
  const [form, setForm] = useState(initialValue);
  const [retirementConfirmed, setRetirementConfirmed] = useState(false);
  const [chamberLoadState, setChamberLoadState] =
    useState<ChamberLoadState>("idle");
  const [chamberSummary, setChamberSummary] =
    useState<ClimateChamberEquipmentSummary | null>(null);
  const [chamberError, setChamberError] = useState<string | null>(null);
  const titleId = useId();
  const chamberField = useRef<HTMLSelectElement>(null);

  useEffect(() => {
    if (!open) return;
    setForm(initialValue);
    setRetirementConfirmed(false);
    setChamberLoadState("idle");
    setChamberSummary(null);
    setChamberError(null);
    const frame = window.requestAnimationFrame(() => chamberField.current?.focus());
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [busy, initialValue, onClose, open]);

  if (!open) return null;

  const update = <K extends keyof RefrigerationEquipmentCreateInput>(
    key: K,
    value: RefrigerationEquipmentCreateInput[K],
  ) => {
    setForm((current) => ({ ...current, [key]: value }));
    if (key === "lifecycleStatus" && value !== "retired") {
      setRetirementConfirmed(false);
    }
  };

  const selectClimateChamber = async (nodeId: string) => {
    if (
      mode === "edit" &&
      form.nodeId &&
      nodeId &&
      nodeId !== form.nodeId &&
      !window.confirm(
        "Після зміни кліматичної камери вибрані датчики та вимірювальні прилади буде скинуто. Продовжити?",
      )
    ) {
      return;
    }
    update("nodeId", nodeId);
    setChamberSummary(null);
    setChamberError(null);
    if (!nodeId || !onClimateChamberChange) {
      setChamberLoadState("idle");
      return;
    }
    setChamberLoadState("loading");
    try {
      const summary = await onClimateChamberChange(nodeId);
      setChamberSummary(summary);
      setChamberLoadState("ready");
    } catch (cause) {
      setChamberLoadState("error");
      setChamberError(
        cause instanceof Error
          ? cause.message
          : "Не вдалося завантажити датчики та вимірювальні прилади камери.",
      );
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (form.lifecycleStatus !== "retired" && !form.nodeId) return;
    if (form.lifecycleStatus === "retired" && !retirementConfirmed) return;
    await onSubmit(form);
  };

  const retirementBlocked =
    form.lifecycleStatus === "retired" && !retirementConfirmed;
  const chamberRequired = form.lifecycleStatus !== "retired";
  const passportLocked = mode !== "edit" && !form.nodeId;
  const title =
    mode === "create"
      ? "Нове холодильне обладнання"
      : mode === "duplicate"
        ? "Копія холодильного обладнання"
        : "Редагування паспорта";

  return (
    <div className="fixed inset-0 z-[80] grid place-items-center bg-slate-950/75 p-4 backdrop-blur-sm">
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="max-h-[92vh] w-full max-w-4xl overflow-y-auto rounded-2xl border border-white/10 bg-[#091a31] shadow-[0_32px_100px_rgba(0,0,0,.55)]"
      >
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-white/[0.07] bg-[#091a31]/95 px-5 py-4 backdrop-blur">
          <div>
            <p className="text-[10px] font-semibold tracking-[0.18em] text-cyan-300 uppercase">
              Equipment passport
            </p>
            <h2 id={titleId} className="mt-1 text-lg font-semibold text-white">
              {title}
            </h2>
          </div>
          <RefrigerationIconButton
            label="Закрити форму"
            onClick={onClose}
            disabled={busy}
          >
            <X className="h-4 w-4" />
          </RefrigerationIconButton>
        </header>

        <form onSubmit={submit} className="p-5">
          {mode === "duplicate" ? (
            <div className="mb-5 flex items-start gap-3 rounded-xl border border-blue-400/20 bg-blue-500/10 p-4 text-xs leading-5 text-blue-100">
              <CopyPlus className="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                Перенесено лише технічні параметри паспорта. Оберіть кліматичну
                камеру, перевірте назву, код і розташування та введіть новий
                серійний номер. Датчики, фото, схеми, історія й аудит не
                копіюються.
              </span>
            </div>
          ) : null}

          <div className="mb-5 rounded-2xl border border-cyan-400/20 bg-cyan-500/[0.06] p-4">
            <div className="flex items-start gap-3">
              <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-cyan-300/20 bg-cyan-400/10 text-cyan-200">
                <RadioTower className="h-4 w-4" />
              </div>
              <div className="min-w-0 flex-1">
                <Field
                  label="Кліматична камера"
                  required={chamberRequired}
                  hint={
                    mode === "edit"
                      ? "Зміна потребує відсутності активних bindings"
                      : "Перший крок"
                  }
                >
                  <select
                    ref={chamberField}
                    required={chamberRequired}
                    value={form.nodeId}
                    onChange={(event) =>
                      void selectClimateChamber(event.target.value)
                    }
                    className={inputClass}
                    aria-describedby="climate-chamber-help"
                  >
                    <option value="">Оберіть кліматичну камеру</option>
                    {nodeOptions.map((node) => (
                      <option
                        key={node.nodeId}
                        value={node.nodeId}
                        disabled={mode !== "edit" && node.state !== "active"}
                      >
                        {node.displayName}
                        {node.state !== "active" ? ` · ${node.state}` : ""}
                      </option>
                    ))}
                  </select>
                </Field>
                <div
                  id="climate-chamber-help"
                  className="mt-2 min-h-5 text-[10px] leading-5"
                >
                  {chamberLoadState === "loading" ? (
                    <span className="inline-flex items-center gap-2 text-cyan-200">
                      <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                      Завантаження доступних датчиків і приладів…
                    </span>
                  ) : chamberLoadState === "ready" && chamberSummary ? (
                    <div className="space-y-2">
                      <div className="grid gap-2 sm:grid-cols-3">
                        <CatalogMetric
                          label="Dixell"
                          value={chamberSummary.temperatureControllers}
                        />
                        <CatalogMetric
                          label="Температурні канали"
                          value={chamberSummary.temperatureChannels}
                        />
                        <CatalogMetric
                          label="Лічильники"
                          value={chamberSummary.energyMeters}
                        />
                      </div>
                      {chamberSummary.energyMeterEmptyMessage ? (
                        <p className="text-slate-400">
                          {chamberSummary.energyMeterEmptyMessage}
                        </p>
                      ) : (
                        <p className="text-emerald-300">
                          На схемі будуть показані лише канали та прилади цієї
                          камери.
                        </p>
                      )}
                    </div>
                  ) : chamberLoadState === "error" ? (
                    <span className="text-rose-300">{chamberError}</span>
                  ) : (
                    <span className="text-slate-500">
                      Камера визначає набір доступних датчиків і вимірювальних
                      приладів.
                    </span>
                  )}
                </div>
              </div>
            </div>
          </div>

          {passportLocked ? (
            <p className="mb-4 rounded-xl border border-amber-400/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
              Спочатку оберіть кліматичну камеру. Після цього стане доступним
              паспорт обладнання.
            </p>
          ) : null}

          <fieldset disabled={passportLocked || busy} className="disabled:opacity-45">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <Field label="Назва" required>
                <input
                  required
                  value={form.name}
                  onChange={(event) => update("name", event.target.value)}
                  className={inputClass}
                  placeholder="Вітрина №108-01"
                />
              </Field>
              <Field label="Код обладнання" required>
                <input
                  required
                  value={form.code}
                  onChange={(event) => update("code", event.target.value)}
                  className={inputClass}
                  placeholder="CS-P1250-2026-108-01"
                />
              </Field>
              <Field label="Тип" required>
                <select
                  required
                  value={form.type}
                  onChange={(event) => update("type", event.target.value)}
                  className={inputClass}
                >
                  <option>Холодильна вітрина</option>
                  <option>Холодильна камера</option>
                  <option>Морозильна вітрина</option>
                  <option>Інше холодильне обладнання</option>
                </select>
              </Field>
              <Field label="Лабораторія">
                <input
                  value={form.laboratory}
                  onChange={(event) => update("laboratory", event.target.value)}
                  className={inputClass}
                  placeholder="Лабораторія 1"
                />
              </Field>
              <Field label="Зона">
                <input
                  value={form.zone}
                  onChange={(event) => update("zone", event.target.value)}
                  className={inputClass}
                  placeholder="Зона C"
                />
              </Field>
              <Field
                label="Відображуване розташування"
                required
                hint="Каталог і звіти"
              >
                <input
                  required
                  value={form.location}
                  onChange={(event) => update("location", event.target.value)}
                  className={inputClass}
                  placeholder="Лабораторія 1 · Зона C"
                />
              </Field>
              <Field label="Виробник" required>
                <input
                  required
                  value={form.manufacturer}
                  onChange={(event) => update("manufacturer", event.target.value)}
                  className={inputClass}
                  placeholder="Виробник"
                />
              </Field>
              <Field label="Модель" required>
                <input
                  required
                  value={form.model}
                  onChange={(event) => update("model", event.target.value)}
                  className={inputClass}
                  placeholder="Модель"
                />
              </Field>
              <Field
                label="Серійний номер"
                required
                hint={mode === "duplicate" ? "Новий" : undefined}
              >
                <input
                  required
                  value={form.serialNumber}
                  onChange={(event) => update("serialNumber", event.target.value)}
                  className={inputClass}
                  placeholder="SN-00001"
                />
              </Field>
              <Field label="Температурний клас" required>
                <input
                  required
                  value={form.temperatureClass}
                  onChange={(event) =>
                    update("temperatureClass", event.target.value)
                  }
                  className={inputClass}
                  placeholder="3M1 (0…+5 °C)"
                />
              </Field>
              <Field label="Lifecycle">
                <select
                  value={form.lifecycleStatus}
                  onChange={(event) =>
                    update(
                      "lifecycleStatus",
                      event.target.value as EquipmentLifecycleStatus,
                    )
                  }
                  className={inputClass}
                >
                  <option value="active">Активне</option>
                  <option value="maintenance">Обслуговування</option>
                  {mode === "edit" ? (
                    <option value="retired">Виведене з експлуатації</option>
                  ) : null}
                </select>
              </Field>
              <Field label="Дата встановлення">
                <input
                  type="date"
                  value={form.installedAt}
                  onChange={(event) => update("installedAt", event.target.value)}
                  className={inputClass}
                />
              </Field>
              <Field label="Останнє обслуговування">
                <input
                  type="date"
                  value={form.servicedAt}
                  onChange={(event) => update("servicedAt", event.target.value)}
                  className={inputClass}
                />
              </Field>
              <Field label="Кількість слотів датчиків" hint="0–48">
                <input
                  type="number"
                  min={0}
                  max={48}
                  value={form.totalSensors}
                  onChange={(event) =>
                    update("totalSensors", Number(event.target.value))
                  }
                  className={inputClass}
                />
              </Field>
            </div>
          </fieldset>

          {form.lifecycleStatus === "retired" ? (
            <label className="mt-5 flex items-start gap-3 rounded-xl border border-rose-400/20 bg-rose-400/10 p-4 text-xs text-rose-100">
              <input
                type="checkbox"
                checked={retirementConfirmed}
                onChange={(event) =>
                  setRetirementConfirmed(event.target.checked)
                }
                className="mt-0.5 h-4 w-4 accent-rose-400"
              />
              <span>
                Підтверджую незворотне виведення обладнання з експлуатації.
                Активні bindings буде завершено, чернетка стане read-only,
                історичні фото та опубліковані ревізії залишаться доступними.
              </span>
            </label>
          ) : null}

          {error ? (
            <p
              role="alert"
              className="mt-4 rounded-xl border border-rose-400/20 bg-rose-400/10 px-3 py-2 text-xs text-rose-200"
            >
              {error}
            </p>
          ) : null}

          <footer className="mt-6 flex justify-end gap-2 border-t border-white/[0.07] pt-4">
            <button
              type="button"
              onClick={onClose}
              disabled={busy}
              className="rounded-xl border border-white/10 bg-white/[0.035] px-4 py-2.5 text-xs font-medium text-slate-300 transition hover:bg-white/[0.07] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 disabled:opacity-40"
            >
              Скасувати
            </button>
            <button
              type="submit"
              disabled={
                busy ||
                retirementBlocked ||
                (chamberRequired && !form.nodeId) ||
                chamberLoadState === "loading"
              }
              className="inline-flex items-center gap-2 rounded-xl border border-cyan-300/25 bg-cyan-400/15 px-4 py-2.5 text-xs font-semibold text-cyan-100 transition hover:bg-cyan-400/20 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {mode === "create" ? (
                <Plus className="h-4 w-4" />
              ) : mode === "duplicate" ? (
                <CopyPlus className="h-4 w-4" />
              ) : (
                <Pencil className="h-4 w-4" />
              )}
              {busy
                ? "Збереження…"
                : mode === "create"
                  ? "Створити"
                  : mode === "duplicate"
                    ? "Створити копію"
                    : "Зберегти паспорт"}
            </button>
          </footer>
        </form>
      </section>
    </div>
  );
}

export function DeleteEquipmentDialog({
  equipment,
  busy,
  error,
  onClose,
  onConfirm,
}: {
  equipment: RefrigerationEquipment | null;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onConfirm: () => Promise<void>;
}) {
  const titleId = useId();
  const cancelButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!equipment) return;
    const frame = window.requestAnimationFrame(() =>
      cancelButton.current?.focus(),
    );
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [busy, equipment, onClose]);

  if (!equipment) return null;

  return (
    <div className="fixed inset-0 z-[80] grid place-items-center bg-slate-950/75 p-4 backdrop-blur-sm">
      <section
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="w-full max-w-md rounded-2xl border border-rose-400/20 bg-[#091a31] p-5 shadow-[0_32px_100px_rgba(0,0,0,.55)]"
      >
        <div className="flex items-start gap-4">
          <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl border border-rose-400/20 bg-rose-400/10 text-rose-300">
            <AlertTriangle className="h-5 w-5" />
          </div>
          <div>
            <h2 id={titleId} className="text-base font-semibold text-white">
              Видалити обладнання?
            </h2>
            <p className="mt-2 text-sm leading-6 text-slate-400">
              <span className="font-medium text-slate-200">
                {equipment.name}
              </span>{" "}
              буде прибрано з каталогу. Історичні схеми та аудит залишаться
              збереженими.
            </p>
            <p className="mt-2 text-xs text-slate-600">{equipment.code}</p>
          </div>
        </div>

        {error ? (
          <p
            role="alert"
            className="mt-4 rounded-xl border border-rose-400/20 bg-rose-400/10 px-3 py-2 text-xs text-rose-200"
          >
            {error}
          </p>
        ) : null}

        <footer className="mt-6 flex justify-end gap-2">
          <button
            ref={cancelButton}
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-xl border border-white/10 bg-white/[0.035] px-4 py-2.5 text-xs font-medium text-slate-300 transition hover:bg-white/[0.07] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 disabled:opacity-40"
          >
            Скасувати
          </button>
          <button
            type="button"
            onClick={() => void onConfirm()}
            disabled={busy}
            className="inline-flex items-center gap-2 rounded-xl border border-rose-400/25 bg-rose-400/15 px-4 py-2.5 text-xs font-semibold text-rose-100 transition hover:bg-rose-400/20 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-300 disabled:cursor-wait disabled:opacity-50"
          >
            <Trash2 className="h-4 w-4" />
            {busy ? "Видалення…" : "Видалити"}
          </button>
        </footer>
      </section>
    </div>
  );
}

function equipmentToInput(
  equipment: RefrigerationEquipment,
): RefrigerationEquipmentUpdateInput {
  return {
    code: equipment.code,
    name: equipment.name,
    location: equipment.location,
    laboratory: equipment.laboratory ?? "",
    zone: equipment.zone ?? "",
    nodeId: equipment.nodeId ?? "",
    type: equipment.type,
    manufacturer: equipment.manufacturer,
    model: equipment.model,
    serialNumber: equipment.serialNumber,
    temperatureClass: equipment.temperatureClass,
    installedAt: equipment.installedAt,
    servicedAt: equipment.servicedAt,
    lifecycleStatus: equipment.lifecycleStatus,
    totalSensors: equipment.totalSensors,
  };
}

function CatalogMetric({ label, value }: { label: string; value: number }) {
  return (
    <span className="rounded-lg border border-white/[0.07] bg-white/[0.03] px-2.5 py-2 text-slate-400">
      {label}: <strong className="font-semibold text-slate-100">{value}</strong>
    </span>
  );
}

function Field({
  label,
  hint,
  required,
  children,
}: {
  label: string;
  hint?: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="grid gap-1.5 text-xs font-medium text-slate-300">
      <span className="flex items-center justify-between gap-2">
        <span>
          {label}
          {required ? <span className="ml-1 text-cyan-300">*</span> : null}
        </span>
        {hint ? (
          <span className="text-[10px] font-normal text-slate-600">{hint}</span>
        ) : null}
      </span>
      {children}
    </label>
  );
}

const inputClass =
  "min-h-11 w-full rounded-xl border border-white/10 bg-[#07172c] px-3 py-2.5 text-sm text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-cyan-300/35 focus:ring-2 focus:ring-cyan-300/10 disabled:cursor-not-allowed";
