"use client";

import { AlertTriangle, CheckCircle2, Gauge, RefreshCcw, TimerReset } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type {
  CadenceFamily,
  CadenceFamilyDefault,
  EffectiveCadenceDevice,
} from "@/features/acquisition/cadence-client";
import type { AcquisitionCadenceController } from "@/features/acquisition/use-acquisition-cadence";

const familyLabels: Record<CadenceFamily, string> = {
  xjp60d: "Dixell XJP60D",
  le01mp: "LE-01MP / енергомоніторинг",
};

type CadenceChoice = "10" | "30" | "60" | "custom";

function cadenceChoice(intervalSeconds: number): CadenceChoice {
  if (intervalSeconds === 10 || intervalSeconds === 30 || intervalSeconds === 60) {
    return String(intervalSeconds) as CadenceChoice;
  }
  return "custom";
}

function parseInterval(
  choice: CadenceChoice,
  customValue: string,
  minimum: number,
  maximum: number,
): { value: number | null; error: string | null } {
  const resolved = choice === "custom" ? Number(customValue) : Number(choice);
  if (!Number.isFinite(resolved) || !Number.isInteger(resolved)) {
    return { value: null, error: "Вкажіть цілу кількість секунд." };
  }
  if (resolved < minimum) {
    return { value: null, error: `Мінімальний інтервал — ${minimum} секунд.` };
  }
  if (resolved > maximum) {
    return { value: null, error: `Максимальний інтервал — ${maximum} секунд.` };
  }
  return { value: resolved, error: null };
}

function IntervalEditor({
  intervalSeconds,
  minimum,
  maximum,
  disabled,
  inheritedLabel,
  onApply,
  onInherit,
}: {
  intervalSeconds: number;
  minimum: number;
  maximum: number;
  disabled: boolean;
  inheritedLabel?: string;
  onApply: (value: number) => Promise<boolean>;
  onInherit?: () => Promise<boolean>;
}) {
  const [choice, setChoice] = useState<CadenceChoice>(cadenceChoice(intervalSeconds));
  const [customValue, setCustomValue] = useState(String(intervalSeconds));
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    setChoice(cadenceChoice(intervalSeconds));
    setCustomValue(String(intervalSeconds));
    setLocalError(null);
  }, [intervalSeconds]);

  const parsed = parseInterval(choice, customValue, minimum, maximum);
  const dirty = parsed.value !== null && parsed.value !== intervalSeconds;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Інтервал фізичного опитування">
        {[10, 30, 60].map((seconds) => (
          <button
            key={seconds}
            type="button"
            disabled={disabled}
            onClick={() => {
              setChoice(String(seconds) as CadenceChoice);
              setLocalError(null);
            }}
            className={`rounded-xl border px-3 py-2 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-45 ${
              choice === String(seconds)
                ? "border-cyan-300/35 bg-cyan-400/10 text-cyan-100"
                : "border-white/10 bg-white/[0.025] text-slate-300 hover:border-cyan-300/20"
            }`}
          >
            {seconds} с
          </button>
        ))}
        <button
          type="button"
          disabled={disabled}
          onClick={() => {
            setChoice("custom");
            setLocalError(null);
          }}
          className={`rounded-xl border px-3 py-2 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-45 ${
            choice === "custom"
              ? "border-cyan-300/35 bg-cyan-400/10 text-cyan-100"
              : "border-white/10 bg-white/[0.025] text-slate-300 hover:border-cyan-300/20"
          }`}
        >
          Custom
        </button>
      </div>

      {choice === "custom" ? (
        <label className="block max-w-xs text-xs text-slate-400">
          Інтервал, секунд
          <input
            type="number"
            min={minimum}
            max={maximum}
            step={1}
            value={customValue}
            disabled={disabled}
            onChange={(event) => {
              setCustomValue(event.target.value);
              setLocalError(null);
            }}
            className="mt-1.5 w-full rounded-xl border border-white/10 bg-black/20 px-3 py-2.5 text-sm text-white outline-none focus:border-cyan-300/35 disabled:cursor-not-allowed disabled:opacity-50"
          />
        </label>
      ) : null}

      {localError ?? parsed.error ? (
        <p className="text-xs text-rose-300" role="alert">
          {localError ?? parsed.error}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={disabled || !dirty || parsed.error !== null || parsed.value === null}
          onClick={() => {
            if (parsed.value === null || parsed.error) {
              setLocalError(parsed.error ?? "Некоректний інтервал.");
              return;
            }
            void onApply(parsed.value);
          }}
          className="rounded-xl bg-blue-500 px-3.5 py-2 text-xs font-medium text-white transition hover:bg-blue-400 disabled:cursor-not-allowed disabled:opacity-45"
        >
          Застосувати
        </button>
        {onInherit ? (
          <button
            type="button"
            disabled={disabled}
            onClick={() => void onInherit()}
            className="rounded-xl border border-white/10 px-3.5 py-2 text-xs text-slate-300 transition hover:border-cyan-300/25 disabled:cursor-not-allowed disabled:opacity-45"
          >
            {inheritedLabel ?? "Повернути успадковане"}
          </button>
        ) : null}
      </div>
    </div>
  );
}

function FamilyDefaultCard({
  item,
  minimum,
  maximum,
  disabled,
  onApply,
}: {
  item: CadenceFamilyDefault;
  minimum: number;
  maximum: number;
  disabled: boolean;
  onApply: (value: number) => Promise<boolean>;
}) {
  return (
    <article className="rounded-2xl border border-white/[0.07] bg-black/10 p-4">
      <div className="mb-4">
        <p className="text-xs tracking-[0.14em] text-cyan-300 uppercase">{item.busId}</p>
        <h3 className="mt-1 text-sm font-medium text-white">{familyLabels[item.deviceFamily]}</h3>
        <p className="mt-1 text-xs text-slate-500">Family default · {item.intervalSeconds} с</p>
      </div>
      <IntervalEditor
        intervalSeconds={item.intervalSeconds}
        minimum={minimum}
        maximum={maximum}
        disabled={disabled}
        onApply={onApply}
      />
    </article>
  );
}

function DeviceCard({
  device,
  inheritedInterval,
  minimum,
  maximum,
  disabled,
  onApply,
  onInherit,
}: {
  device: EffectiveCadenceDevice;
  inheritedInterval: number;
  minimum: number;
  maximum: number;
  disabled: boolean;
  onApply: (value: number) => Promise<boolean>;
  onInherit: () => Promise<boolean>;
}) {
  const overridden = device.cadenceSource === "device_override";
  return (
    <article className="rounded-2xl border border-white/[0.07] bg-black/10 p-4">
      <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="text-sm font-medium text-white">{device.deviceId}</h3>
          <p className="mt-1 text-xs text-slate-500">
            {familyLabels[device.deviceFamily]} · {device.busId} · {device.lifecycle}
          </p>
        </div>
        <span className="w-fit rounded-full border border-white/10 bg-white/[0.035] px-2.5 py-1 text-[11px] text-slate-300">
          {overridden ? `Override ${device.effectiveIntervalSeconds} с` : `Успадковано ${inheritedInterval} с`}
        </span>
      </div>
      <IntervalEditor
        intervalSeconds={device.effectiveIntervalSeconds}
        minimum={minimum}
        maximum={maximum}
        disabled={disabled}
        inheritedLabel={`Успадкувати ${inheritedInterval} с`}
        onApply={onApply}
        onInherit={overridden ? onInherit : undefined}
      />
    </article>
  );
}

export function AcquisitionCadencePanel({
  controller,
  canManage,
}: {
  controller: AcquisitionCadenceController;
  canManage: boolean;
}) {
  const configuration = controller.configuration;
  const defaultsByKey = useMemo(
    () =>
      new Map(
        (configuration?.familyDefaults ?? []).map((item) => [
          `${item.busId}:${item.deviceFamily}`,
          item.intervalSeconds,
        ]),
      ),
    [configuration],
  );

  return (
    <section
      aria-labelledby="acquisition-cadence-heading"
      className="mb-5 rounded-3xl border border-cyan-300/10 bg-[#091a31]/90 p-5 shadow-2xl shadow-black/20 sm:p-6"
    >
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="max-w-3xl">
          <div className="flex items-start gap-3">
            <div className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl border border-cyan-300/15 bg-cyan-400/[0.07]">
              <TimerReset className="h-5 w-5 text-cyan-200" />
            </div>
            <div>
              <p className="text-xs tracking-[0.18em] text-cyan-300 uppercase">Data collection</p>
              <h2 id="acquisition-cadence-heading" className="mt-1 text-xl font-semibold text-white">
                Фізичний інтервал опитування
              </h2>
            </div>
          </div>
          <p className="mt-4 text-sm leading-6 text-slate-400">
            Цей параметр змінює частоту реальних read-only Modbus запитів Device Agent. Refresh графіків,
            вибір 24 год / 7 днів, Saved Dashboard та відкриття інших браузерів не змінюють фізичне
            опитування.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void controller.refresh()}
          disabled={controller.isLoading || controller.isSaving}
          className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/10 px-3.5 py-2.5 text-xs text-slate-300 transition hover:border-cyan-300/25 hover:text-white disabled:cursor-wait disabled:opacity-50"
        >
          <RefreshCcw className={`h-4 w-4 ${controller.isLoading ? "animate-spin" : ""}`} />
          Оновити канонічний стан
        </button>
      </div>

      {!canManage ? (
        <div className="mt-5 rounded-2xl border border-amber-300/15 bg-amber-400/[0.05] p-4 text-xs leading-5 text-amber-100">
          Доступ лише для перегляду. Зміна фізичного polling потребує дозволу equipment.manage.
        </div>
      ) : null}

      {controller.error ? (
        <div className="mt-5 rounded-2xl border border-rose-300/15 bg-rose-400/[0.05] p-4" role="alert">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-rose-300" />
            <div>
              <p className="text-sm font-medium text-rose-100">
                {controller.error.code === "revision_conflict"
                  ? "Конфлікт версії cadence policy"
                  : controller.error.code === "acquisition_capacity_exceeded"
                    ? "Запитаний інтервал небезпечний для активної RS-485 шини"
                    : "Не вдалося виконати cadence operation"}
              </p>
              <p className="mt-1 text-xs leading-5 text-rose-100/70">{controller.error.message}</p>
              {controller.error.capacity?.buses
                .filter((bus) => !bus.safe)
                .map((bus) => (
                  <p key={bus.busId} className="mt-2 text-xs text-rose-100/80">
                    {bus.busId}: оцінка {bus.estimatedUtilizationPercent}% при дозволених {bus.maximumAllowedUtilizationPercent}%
                    {bus.recommendedMinimumIntervalSeconds
                      ? ` · рекомендовано не швидше ${bus.recommendedMinimumIntervalSeconds} с`
                      : ""}
                  </p>
                ))}
            </div>
          </div>
        </div>
      ) : null}

      {controller.isLoading && !configuration ? (
        <p className="mt-6 text-sm text-slate-500">Завантаження persisted cadence policy…</p>
      ) : configuration ? (
        <>
          <div className="mt-6 flex flex-wrap items-center gap-3 text-xs text-slate-500">
            <span>Registry revision: {configuration.registryRevision}</span>
            <span>•</span>
            <span>Оновлено: {configuration.updatedAt}</span>
            <span>•</span>
            <span>Custom: {configuration.customMinSeconds}–{configuration.maximumSeconds} с</span>
          </div>

          <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {configuration.capacity.buses.map((bus) => (
              <div
                key={bus.busId}
                className={`rounded-2xl border p-4 ${
                  bus.safe
                    ? "border-emerald-300/15 bg-emerald-400/[0.04]"
                    : "border-rose-300/15 bg-rose-400/[0.04]"
                }`}
              >
                <div className="flex items-start gap-3">
                  {bus.safe ? (
                    <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-300" />
                  ) : (
                    <Gauge className="mt-0.5 h-4 w-4 text-rose-300" />
                  )}
                  <div>
                    <p className="text-sm font-medium text-slate-100">{bus.busId}</p>
                    <p className="mt-1 text-xs text-slate-500">
                      Bus load {bus.estimatedUtilizationPercent}% / {bus.maximumAllowedUtilizationPercent}% · {bus.activeDeviceCount} devices
                    </p>
                    <p className="mt-1 text-[11px] text-slate-600">Timing: {bus.requestBudgetSource}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div className="mt-7">
            <h3 className="text-sm font-medium text-white">Defaults за фізичною шиною та family</h3>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              Усі логічні канали одного physical device використовують effective device cadence; окремого channel polling control немає.
            </p>
            <div className="mt-4 grid gap-4 xl:grid-cols-2">
              {configuration.familyDefaults.map((item) => (
                <FamilyDefaultCard
                  key={`${item.busId}:${item.deviceFamily}`}
                  item={item}
                  minimum={configuration.customMinSeconds}
                  maximum={configuration.maximumSeconds}
                  disabled={!canManage || controller.isSaving}
                  onApply={(value) => controller.setFamilyDefault(item.busId, item.deviceFamily, value)}
                />
              ))}
            </div>
          </div>

          <div className="mt-7">
            <h3 className="text-sm font-medium text-white">Overrides фізичних devices</h3>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              Override застосовується до physical device, не до temperature/electrical UI channel. Його можна повернути до inherited family default.
            </p>
            <div className="mt-4 grid gap-4 xl:grid-cols-2">
              {configuration.effectiveDevices.map((device) => {
                const inheritedInterval =
                  defaultsByKey.get(`${device.busId}:${device.deviceFamily}`) ?? device.effectiveIntervalSeconds;
                return (
                  <DeviceCard
                    key={device.deviceId}
                    device={device}
                    inheritedInterval={inheritedInterval}
                    minimum={configuration.customMinSeconds}
                    maximum={configuration.maximumSeconds}
                    disabled={!canManage || controller.isSaving}
                    onApply={(value) => controller.setDeviceOverride(device.deviceId, value)}
                    onInherit={() => controller.setDeviceOverride(device.deviceId, null)}
                  />
                );
              })}
            </div>
          </div>
        </>
      ) : (
        <div className="mt-6 rounded-2xl border border-amber-300/15 bg-amber-400/[0.04] p-4 text-sm text-amber-100/80">
          Canonical cadence policy недоступна. Жодна фізична mutation не виконується.
        </div>
      )}
    </section>
  );
}
