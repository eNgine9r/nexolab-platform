"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { AlertTriangle, Plus, Trash2, X } from "lucide-react";

import type { RefrigerationEquipment } from "@/data/refrigeration";
import type { RefrigerationEquipmentCreateInput } from "@/features/refrigeration/equipment-repository";

const initialForm: RefrigerationEquipmentCreateInput = {
  code: "",
  name: "",
  location: "",
  type: "Холодильна вітрина",
  manufacturer: "",
  model: "",
  serialNumber: "",
  temperatureClass: "",
  installedAt: "",
  servicedAt: "",
  totalSensors: 0,
};

export function CreateEquipmentDialog({
  open,
  busy,
  error,
  onClose,
  onSubmit,
}: {
  open: boolean;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (input: RefrigerationEquipmentCreateInput) => Promise<void>;
}) {
  const [form, setForm] = useState(initialForm);
  const titleId = useId();
  const firstField = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setForm(initialForm);
    const frame = window.requestAnimationFrame(() => firstField.current?.focus());
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [busy, onClose, open]);

  if (!open) return null;

  const update = <K extends keyof RefrigerationEquipmentCreateInput>(
    key: K,
    value: RefrigerationEquipmentCreateInput[K],
  ) => setForm((current) => ({ ...current, [key]: value }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    await onSubmit(form);
  };

  return (
    <div className="fixed inset-0 z-[80] grid place-items-center bg-slate-950/75 p-4 backdrop-blur-sm">
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="max-h-[92vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-white/10 bg-[#091a31] shadow-[0_32px_100px_rgba(0,0,0,.55)]"
      >
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-white/[0.07] bg-[#091a31]/95 px-5 py-4 backdrop-blur">
          <div>
            <p className="text-[10px] font-semibold tracking-[0.18em] text-cyan-300 uppercase">Equipment registry</p>
            <h2 id={titleId} className="mt-1 text-lg font-semibold text-white">
              Нове холодильне обладнання
            </h2>
          </div>
          <button
            type="button"
            aria-label="Закрити форму"
            title="Закрити"
            onClick={onClose}
            disabled={busy}
            className="grid h-10 w-10 place-items-center rounded-xl border border-white/10 bg-white/[0.035] text-slate-400 transition hover:border-white/20 hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 disabled:opacity-40"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <form onSubmit={submit} className="p-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Назва" required>
              <input
                ref={firstField}
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
            <Field label="Розташування" required>
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
            <Field label="Серійний номер" required>
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
                onChange={(event) => update("temperatureClass", event.target.value)}
                className={inputClass}
                placeholder="3M1 (0…+5 °C)"
              />
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
            <Field label="Кількість датчиків" hint="0–48">
              <input
                type="number"
                min={0}
                max={48}
                value={form.totalSensors}
                onChange={(event) => update("totalSensors", Number(event.target.value))}
                className={inputClass}
              />
            </Field>
          </div>

          {error ? (
            <p role="alert" className="mt-4 rounded-xl border border-rose-400/20 bg-rose-400/10 px-3 py-2 text-xs text-rose-200">
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
              disabled={busy}
              className="inline-flex items-center gap-2 rounded-xl border border-cyan-300/25 bg-cyan-400/15 px-4 py-2.5 text-xs font-semibold text-cyan-100 transition hover:bg-cyan-400/20 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 disabled:cursor-wait disabled:opacity-50"
            >
              <Plus className="h-4 w-4" />
              {busy ? "Створення…" : "Створити"}
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
    const frame = window.requestAnimationFrame(() => cancelButton.current?.focus());
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
              <span className="font-medium text-slate-200">{equipment.name}</span> буде прибрано з каталогу. Історичні схеми та аудит залишаться збереженими.
            </p>
            <p className="mt-2 text-xs text-slate-600">{equipment.code}</p>
          </div>
        </div>

        {error ? (
          <p role="alert" className="mt-4 rounded-xl border border-rose-400/20 bg-rose-400/10 px-3 py-2 text-xs text-rose-200">
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
        {hint ? <span className="font-normal text-slate-600">{hint}</span> : null}
      </span>
      {children}
    </label>
  );
}

const inputClass =
  "min-h-11 rounded-xl border border-white/10 bg-[#07162b] px-3 py-2.5 text-sm text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-cyan-300/40 focus:ring-2 focus:ring-cyan-300/10";
