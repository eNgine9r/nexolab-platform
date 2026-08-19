"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Save, X } from "lucide-react";

import type { EquipmentRegistryAsset } from "@/features/equipment/asset-registry";
import type {
  ClimateCatalogRepository,
  MeasurementDeviceMetadataUpdate,
  PhysicalSensorMetadataUpdate,
} from "@/features/refrigeration/climate-catalog-repository";
import type {
  RefrigerationEquipmentRepository,
  RefrigerationEquipmentUpdateInput,
} from "@/features/refrigeration/equipment-repository";

export function EquipmentMetadataEditor({
  asset,
  equipmentRepository,
  climateCatalogRepository,
  onSaved,
  onCancel,
  onDirtyChange,
}: {
  asset: EquipmentRegistryAsset;
  equipmentRepository: RefrigerationEquipmentRepository | null;
  climateCatalogRepository: ClimateCatalogRepository | null;
  onSaved: () => void;
  onCancel: () => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const initial = useMemo(() => editorValues(asset), [asset]);
  const [values, setValues] = useState<EditorValues>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirty = JSON.stringify(values) !== JSON.stringify(initial);

  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);

  const update = (key: string, value: string) => {
    setValues((current) => ({ ...current, [key]: value }));
    setError(null);
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (asset.category === "refrigeration-equipment") {
        if (!equipmentRepository) throw new Error("Канонічний каталог холодильного обладнання недоступний.");
        const source = asset.source;
        const input: RefrigerationEquipmentUpdateInput = {
          code: source.code,
          name: required(values.name, "Назва"),
          location: required(values.location, "Розташування"),
          laboratory: values.laboratory.trim(),
          zone: values.zone.trim(),
          climateChamberId: source.climateChamberId ?? undefined,
          nodeId: source.nodeId ?? source.climateChamberId ?? "",
          type: source.type,
          manufacturer: required(values.manufacturer, "Виробник"),
          model: required(values.model, "Модель"),
          serialNumber: values.serialNumber.trim(),
          temperatureClass: values.temperatureClass.trim(),
          installedAt: source.installedAt,
          servicedAt: source.servicedAt,
          lifecycleStatus: source.lifecycleStatus,
          totalSensors: source.totalSensors,
        };
        await equipmentRepository.update(source.id, input, source.version);
      } else if (asset.category === "physical-sensor") {
        if (!climateCatalogRepository) throw new Error("Канонічний climate catalog недоступний.");
        const input: PhysicalSensorMetadataUpdate = {
          inventoryNumber: required(values.inventoryNumber, "Inventory number"),
          serialNumber: optional(values.serialNumber),
          calibrationStatus: values.calibrationStatus as PhysicalSensorMetadataUpdate["calibrationStatus"],
        };
        await climateCatalogRepository.updatePhysicalSensor(
          asset.chamber.id,
          asset.source.id,
          input,
          asset.source.version,
        );
      } else {
        if (!climateCatalogRepository) throw new Error("Канонічний climate catalog недоступний.");
        const input: MeasurementDeviceMetadataUpdate = {
          displayName: required(values.displayName, "Назва"),
          designation: optional(values.designation),
          manufacturer: required(values.manufacturer, "Виробник"),
          model: required(values.model, "Модель"),
        };
        await climateCatalogRepository.updateMeasurementDevice(
          asset.chamber.id,
          asset.source.id,
          input,
          asset.source.version,
        );
      }
      onDirtyChange(false);
      onSaved();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Метадані обладнання не оновлено.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-label={`Редагування ${asset.primaryIdentifier}`} className="space-y-4">
      <div className="rounded-2xl border border-cyan-300/15 bg-cyan-400/[0.06] p-4">
        <h3 className="text-sm font-semibold text-cyan-100">Адміністративні метадані</h3>
        <p className="mt-1 text-xs leading-5 text-cyan-100/65">
          Ця форма не змінює Modbus Unit ID, RS-485 bus/serial parameters, register mapping, acquisition
          enablement, polling cadence або hardware state.
        </p>
      </div>

      {asset.category === "refrigeration-equipment" ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Назва" value={values.name} onChange={(value) => update("name", value)} required />
          <Field
            label="Розташування"
            value={values.location}
            onChange={(value) => update("location", value)}
            required
          />
          <Field
            label="Лабораторія"
            value={values.laboratory}
            onChange={(value) => update("laboratory", value)}
          />
          <Field label="Зона" value={values.zone} onChange={(value) => update("zone", value)} />
          <Field
            label="Виробник"
            value={values.manufacturer}
            onChange={(value) => update("manufacturer", value)}
            required
          />
          <Field label="Модель" value={values.model} onChange={(value) => update("model", value)} required />
          <Field
            label="Серійний номер"
            value={values.serialNumber}
            onChange={(value) => update("serialNumber", value)}
          />
          <Field
            label="Температурний клас"
            value={values.temperatureClass}
            onChange={(value) => update("temperatureClass", value)}
          />
        </div>
      ) : asset.category === "physical-sensor" ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            label="Inventory number"
            value={values.inventoryNumber}
            onChange={(value) => update("inventoryNumber", value)}
            required
          />
          <Field
            label="Серійний номер"
            value={values.serialNumber}
            onChange={(value) => update("serialNumber", value)}
          />
          <label className="text-xs text-slate-400 sm:col-span-2">
            Статус калібрування
            <select
              aria-label="Статус калібрування"
              value={values.calibrationStatus}
              onChange={(event) => update("calibrationStatus", event.target.value)}
              className={inputClassName}
            >
              <option value="untracked">Не відстежується</option>
              <option value="current">Актуальне</option>
              <option value="due">Наближається термін</option>
              <option value="expired">Прострочене</option>
            </select>
          </label>
          <ReadOnlyBoundary
            text={`Позиція ${asset.source.sensorPosition} і channel mapping залишаються read-only.`}
          />
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            label="Назва"
            value={values.displayName}
            onChange={(value) => update("displayName", value)}
            required
          />
          <Field
            label="Позначення"
            value={values.designation}
            onChange={(value) => update("designation", value)}
          />
          <Field
            label="Виробник"
            value={values.manufacturer}
            onChange={(value) => update("manufacturer", value)}
            required
          />
          <Field label="Модель" value={values.model} onChange={(value) => update("model", value)} required />
          <ReadOnlyBoundary
            text={`Modbus Unit ID ${asset.source.unitId} і transport identity залишаються read-only.`}
          />
        </div>
      )}

      {error ? (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-xl border border-rose-300/20 bg-rose-400/10 p-3 text-xs text-rose-100"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      ) : null}

      <div className="flex flex-wrap justify-end gap-2 border-t border-white/[0.07] pt-4">
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="inline-flex h-10 items-center gap-2 rounded-xl border border-white/10 px-4 text-xs font-semibold text-slate-300 hover:bg-white/[0.05] disabled:opacity-50"
        >
          <X className="h-4 w-4" />
          Скасувати
        </button>
        <button
          type="button"
          onClick={() => void save()}
          disabled={busy || !dirty}
          className="inline-flex h-10 items-center gap-2 rounded-xl bg-blue-500 px-4 text-xs font-semibold text-white hover:bg-blue-400 disabled:cursor-not-allowed disabled:opacity-45"
        >
          <Save className="h-4 w-4" />
          {busy ? "Збереження…" : "Зберегти"}
        </button>
      </div>
    </section>
  );
}

const inputClassName =
  "mt-1.5 h-10 w-full rounded-xl border border-white/10 bg-[#06142a] px-3 text-sm text-slate-100 outline-none focus:border-cyan-300/35 focus:ring-2 focus:ring-cyan-300/10";

function Field({
  label,
  value,
  onChange,
  required: isRequired = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
}) {
  return (
    <label className="text-xs text-slate-400">
      {label}
      <input
        aria-label={label}
        value={value}
        required={isRequired}
        onChange={(event) => onChange(event.target.value)}
        className={inputClassName}
      />
    </label>
  );
}

function ReadOnlyBoundary({ text }: { text: string }) {
  return (
    <p className="rounded-xl border border-white/[0.07] p-3 text-xs text-slate-500 sm:col-span-2">{text}</p>
  );
}

type EditorValues = Record<string, string>;

function editorValues(asset: EquipmentRegistryAsset): EditorValues {
  if (asset.category === "refrigeration-equipment") {
    return {
      name: asset.source.name,
      location: asset.source.location,
      laboratory: asset.source.laboratory ?? "",
      zone: asset.source.zone ?? "",
      manufacturer: asset.source.manufacturer,
      model: asset.source.model,
      serialNumber: asset.source.serialNumber,
      temperatureClass: asset.source.temperatureClass,
    };
  }
  if (asset.category === "physical-sensor") {
    return {
      inventoryNumber: asset.source.inventoryNumber,
      serialNumber: asset.source.serialNumber ?? "",
      calibrationStatus: asset.source.calibrationStatus,
    };
  }
  return {
    displayName: asset.source.displayName,
    designation: asset.source.designation ?? "",
    manufacturer: asset.source.manufacturer,
    model: asset.source.model,
  };
}

function required(value: string | undefined, label: string): string {
  const normalized = value?.trim() ?? "";
  if (!normalized) throw new Error(`${label}: поле є обов’язковим.`);
  return normalized;
}

function optional(value: string | undefined): string | null {
  return value?.trim() || null;
}
