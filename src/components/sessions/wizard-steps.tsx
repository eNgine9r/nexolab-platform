import type { ReactNode } from "react";
import {
  ClipboardCheck,
  Gauge,
  Layers3,
  LoaderCircle,
  RadioTower,
  RefreshCw,
  SlidersHorizontal,
} from "lucide-react";

import { TelemetryPointSelector } from "@/components/telemetry-selection/telemetry-point-selector";
import type { TelemetryPointHierarchy } from "@/features/telemetry-selection/hierarchy";
import type { SessionStageType } from "@/lib/sessions/types";

import { STAGE_TYPES, type SessionWizardForm } from "./wizard-model";

export interface WizardStepProps {
  form: SessionWizardForm;
  update: <K extends keyof SessionWizardForm>(key: K, value: SessionWizardForm[K]) => void;
}

export function GeneralStep({ form, update }: WizardStepProps) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Field label="Номер випробування" required>
        <input
          className="form-input font-mono"
          value={form.sessionNumber}
          onChange={(event) => update("sessionNumber", event.target.value)}
        />
      </Field>
      <Field label="Замовник" required>
        <input
          className="form-input"
          value={form.customer}
          onChange={(event) => update("customer", event.target.value)}
          placeholder="Назва компанії"
        />
      </Field>
      <Field label="Назва сесії" required className="md:col-span-2">
        <input
          className="form-input"
          value={form.title}
          onChange={(event) => update("title", event.target.value)}
        />
      </Field>
      <Field label="Оператор">
        <input
          className="form-input"
          value={form.operatorId}
          onChange={(event) => update("operatorId", event.target.value)}
        />
      </Field>
      <Field label="Відповідальний інженер">
        <input
          className="form-input"
          value={form.engineerId}
          onChange={(event) => update("engineerId", event.target.value)}
        />
      </Field>
    </div>
  );
}

export function ObjectStep({ form, update }: WizardStepProps) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Field label="Об’єкт випробування" required>
        <input
          className="form-input"
          value={form.testObject}
          onChange={(event) => update("testObject", event.target.value)}
        />
      </Field>
      <Field label="Модель" required>
        <input
          className="form-input"
          value={form.model}
          onChange={(event) => update("model", event.target.value)}
        />
      </Field>
      <Field label="Серійний номер" required>
        <input
          className="form-input"
          value={form.serialNumber}
          onChange={(event) => update("serialNumber", event.target.value)}
        />
      </Field>
      <InfoCard title="Node assignment" value="edge-01" detail="Production Device Agent · fixed M4 scope" />
    </div>
  );
}

export function MethodStep({ form, update }: WizardStepProps) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Field label="Нормативний документ" required>
        <input
          className="form-input"
          value={form.standard}
          onChange={(event) => update("standard", event.target.value)}
        />
      </Field>
      <Field label="Методика" required>
        <input
          className="form-input"
          value={form.method}
          onChange={(event) => update("method", event.target.value)}
        />
      </Field>
      <div className="rounded-2xl border border-blue-300/10 bg-blue-400/[0.04] p-5 md:col-span-2">
        <ClipboardCheck className="h-5 w-5 text-cyan-300" />
        <h3 className="mt-3 text-sm font-semibold text-white">Versioned method metadata</h3>
        <p className="mt-1 text-[11px] leading-5 text-slate-400">
          Sampling policy, register-profile versions, bindings і limits увійдуть до immutable start snapshot.
        </p>
      </div>
    </div>
  );
}

type EquipmentStepProps = WizardStepProps & {
  hierarchy: TelemetryPointHierarchy;
  eligibleCount: number;
  selectionStatus: "loading" | "ready" | "error";
  selectionError: Error | null;
  onRetry: () => void;
};

export function EquipmentStep({
  form,
  update,
  hierarchy,
  eligibleCount,
  selectionStatus,
  selectionError,
  onRetry,
}: EquipmentStepProps) {
  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-emerald-300/15 bg-emerald-400/[0.04] p-5">
        <div className="flex items-center gap-2">
          <RadioTower className="h-5 w-5 text-emerald-300" />
          <h3 className="text-sm font-semibold text-white">Validated session telemetry</h3>
        </div>
        <p className="mt-2 text-[11px] leading-5 text-slate-400">
          Доступні лише реальні канали inventory, які одночасно входять до server-authoritative Test Sessions contract.
          Вибір не запускає фізичне опитування і не змінює acquisition scheduler.
        </p>
        <div className="mt-3 flex flex-wrap gap-2 text-[9px] text-slate-500">
          <span className="rounded-full border border-white/[0.07] px-2.5 py-1">Eligible: {eligibleCount}</span>
          <span className="rounded-full border border-white/[0.07] px-2.5 py-1">
            Selected: {form.selectedTelemetryKeys.length}
          </span>
        </div>
      </div>

      {selectionStatus === "loading" && (
        <div className="flex min-h-44 items-center justify-center rounded-2xl border border-white/[0.06] bg-white/[0.02] text-[11px] text-slate-400">
          <LoaderCircle className="mr-2 h-4 w-4 animate-spin text-cyan-300" />
          Завантаження локального inventory та session contract…
        </div>
      )}

      {selectionStatus === "error" && (
        <div className="rounded-2xl border border-red-300/15 bg-red-400/[0.04] p-5">
          <p className="text-[11px] font-semibold text-red-200">Не вдалося завантажити доступні telemetry points</p>
          <p className="mt-2 text-[10px] leading-5 text-slate-400">
            {selectionError?.message ?? "Невідома помилка локального API."}
          </p>
          <button className="secondary-button mt-4 gap-2" type="button" onClick={onRetry}>
            <RefreshCw className="h-3.5 w-3.5" />
            Повторити
          </button>
        </div>
      )}

      {selectionStatus === "ready" && eligibleCount === 0 && (
        <div className="rounded-2xl border border-amber-300/15 bg-amber-400/[0.04] p-5 text-[10px] leading-5 text-slate-400">
          У поточному локальному inventory немає каналів, що збігаються з валідованим Test Sessions contract. Перехід
          далі заблоковано — fallback на всі 34 канали не виконується.
        </div>
      )}

      {selectionStatus === "ready" && eligibleCount > 0 && (
        <TelemetryPointSelector
          hierarchy={hierarchy}
          value={form.selectedTelemetryKeys}
          onConfirm={(selected) => update("selectedTelemetryKeys", selected)}
          title="Telemetry points для сесії"
          maxSelection={eligibleCount}
        />
      )}
    </div>
  );
}

export function SamplingStep({ form, update }: WizardStepProps) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <NumberField
        label="Інтервал запису, секунд"
        value={form.samplingSeconds}
        min={1}
        max={3600}
        onChange={(value) => update("samplingSeconds", value)}
      />
      <div className="rounded-2xl border border-white/[0.06] bg-white/[0.025] p-5">
        <Gauge className="h-5 w-5 text-cyan-300" />
        <p className="mt-3 text-sm font-semibold text-white">Fixed interval</p>
        <p className="mt-1 text-[10px] leading-5 text-slate-500">
          Pause призупиняє workflow, але не telemetry collection.
        </p>
      </div>
    </div>
  );
}

export function LimitsStep({ form, update }: WizardStepProps) {
  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-sm font-semibold text-white">Температура 106-03 / 106-04</h3>
        <div className="mt-3 grid gap-3 sm:grid-cols-4">
          <NumberField
            label="Нижня, °C"
            value={form.temperatureLower}
            onChange={(value) => update("temperatureLower", value)}
          />
          <NumberField
            label="Верхня, °C"
            value={form.temperatureUpper}
            onChange={(value) => update("temperatureUpper", value)}
          />
          <NumberField
            label="Hysteresis"
            value={form.temperatureHysteresis}
            step={0.1}
            onChange={(value) => update("temperatureHysteresis", value)}
          />
          <NumberField
            label="Duration, s"
            value={form.temperatureDurationSeconds}
            onChange={(value) => update("temperatureDurationSeconds", value)}
          />
        </div>
      </div>
      <div className="border-t border-white/[0.055] pt-5">
        <h3 className="text-sm font-semibold text-white">Активна потужність LE-01MP</h3>
        <div className="mt-3 max-w-xs">
          <NumberField
            label="Верхня межа, W"
            value={form.powerUpper}
            onChange={(value) => update("powerUpper", value)}
          />
        </div>
      </div>
      <div className="rounded-2xl border border-cyan-300/10 bg-cyan-400/[0.035] p-4 text-[10px] leading-5 text-slate-400">
        <SlidersHorizontal className="mr-2 inline h-4 w-4 text-cyan-300" />
        Limits створюються як append-only version 1.
      </div>
    </div>
  );
}

export function StagesStep({ form, update }: WizardStepProps) {
  const changeStage = (
    index: number,
    field: "name" | "stage_type" | "planned_duration_minutes",
    value: string | number | SessionStageType,
  ) => {
    update(
      "stages",
      form.stages.map((stage, stageIndex) => (stageIndex === index ? { ...stage, [field]: value } : stage)),
    );
  };

  return (
    <div className="space-y-3">
      {form.stages.map((stage, index) => (
        <div
          key={stage.sequence_index}
          className="grid gap-3 rounded-2xl border border-white/[0.06] bg-white/[0.02] p-4 md:grid-cols-[44px_1fr_180px_130px] md:items-end"
        >
          <div className="grid h-10 w-10 place-items-center rounded-xl border border-blue-300/15 bg-blue-400/[0.05] text-[11px] font-semibold text-cyan-200">
            {index + 1}
          </div>
          <Field label="Назва">
            <input
              className="form-input"
              value={stage.name}
              onChange={(event) => changeStage(index, "name", event.target.value)}
            />
          </Field>
          <Field label="Тип">
            <select
              className="form-input"
              value={stage.stage_type}
              onChange={(event) => changeStage(index, "stage_type", event.target.value as SessionStageType)}
            >
              {STAGE_TYPES.map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </Field>
          <NumberField
            label="Хвилини"
            value={stage.planned_duration_minutes}
            onChange={(value) => changeStage(index, "planned_duration_minutes", value)}
          />
        </div>
      ))}
      <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-4 text-[10px] leading-5 text-slate-500">
        <Layers3 className="mr-2 inline h-4 w-4 text-cyan-300" />
        Фактичні stage boundaries створюються оператором у live workspace й потрапляють до audit.
      </div>
    </div>
  );
}

export function ReviewStep({ form }: { form: SessionWizardForm }) {
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <ReviewCard title="Сесія" lines={[form.sessionNumber, form.title, form.customer]} />
      <ReviewCard
        title="Об’єкт"
        lines={[form.testObject, `${form.model} · ${form.serialNumber}`, "edge-01"]}
      />
      <ReviewCard
        title="Методика"
        lines={[form.standard, form.method, `${form.samplingSeconds} s sampling`]}
      />
      <ReviewCard
        title="Telemetry bindings"
        lines={[
          `${form.selectedTelemetryKeys.length} selected validated series`,
          "Exact selected subset will be persisted",
          "No fallback to the full 34-series contract",
        ]}
      />
      <ReviewCard
        title="Limits v1"
        lines={[
          `${form.temperatureLower}…${form.temperatureUpper} °C`,
          `Hysteresis ${form.temperatureHysteresis} °C`,
          `Power ≤ ${form.powerUpper} W`,
        ]}
      />
      <ReviewCard
        title="Stage plan"
        lines={form.stages.map(
          (stage) => `${stage.sequence_index + 1}. ${stage.name} · ${stage.planned_duration_minutes} min`,
        )}
      />
    </div>
  );
}

function Field({
  label,
  children,
  required,
  className = "",
}: {
  label: string;
  children: ReactNode;
  required?: boolean;
  className?: string;
}) {
  return (
    <label className={`block ${className}`}>
      <span className="form-label">
        {label}
        {required ? " *" : ""}
      </span>
      {children}
    </label>
  );
}

function NumberField({
  label,
  value,
  step = 1,
  min,
  max,
  onChange,
}: {
  label: string;
  value: number;
  step?: number;
  min?: number;
  max?: number;
  onChange: (value: number) => void;
}) {
  return (
    <Field label={label}>
      <input
        type="number"
        step={step}
        min={min}
        max={max}
        className="form-input"
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </Field>
  );
}

function InfoCard({ title, value, detail }: { title: string; value: string; detail: string }) {
  return (
    <div className="rounded-2xl border border-white/[0.06] bg-white/[0.025] p-4">
      <p className="text-[8px] tracking-[0.12em] text-slate-600 uppercase">{title}</p>
      <p className="mt-2 text-lg font-semibold text-white">{value}</p>
      <p className="mt-1 text-[9px] text-slate-500">{detail}</p>
    </div>
  );
}

function ReviewCard({ title, lines }: { title: string; lines: string[] }) {
  return (
    <div className="rounded-2xl border border-white/[0.06] bg-white/[0.025] p-5">
      <p className="text-[9px] font-semibold tracking-[0.12em] text-cyan-300 uppercase">{title}</p>
      <div className="mt-3 space-y-1.5">
        {lines.map((line, index) => (
          <p
            key={`${line}-${index}`}
            className={index === 0 ? "text-sm font-semibold text-white" : "text-[10px] text-slate-500"}
          >
            {line || "—"}
          </p>
        ))}
      </div>
    </div>
  );
}
