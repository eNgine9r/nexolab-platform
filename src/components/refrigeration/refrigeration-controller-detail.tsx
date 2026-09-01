"use client";

import Link from "next/link";
import { LockKeyhole, RadioTower, ServerCog } from "lucide-react";

import { EMBRACO_METRICS } from "@/features/refrigeration/controller-monitoring";
import type { RefrigerationControllerModel } from "@/features/refrigeration/use-refrigeration-controller";

export function RefrigerationControllerDetail({
  controller,
  equipmentId,
  canCommission,
}: {
  controller: RefrigerationControllerModel;
  equipmentId: string;
  canCommission: boolean;
}) {
  const binding = controller.binding;
  if (controller.bindingLoading)
    return <PanelMessage title="Контролер" text="Завантаження прив’язки контролера…" />;
  if (!binding && controller.latestError)
    return <PanelMessage title="Контролер недоступний" text={controller.latestError} error />;
  if (!binding) {
    return (
      <section className="rounded-2xl border border-white/[0.08] bg-[#081a32] p-8 text-center">
        <RadioTower className="mx-auto h-6 w-6 text-slate-600" />
        <h2 className="mt-3 text-sm font-semibold text-white">○ Контролер не підключено</h2>
        <p className="mt-2 text-xs text-slate-500">
          Чернетка збере профіль і connection intent без live hardware preflight чи активації.
        </p>
        {canCommission ? (
          <Link
            href={`/equipment/onboarding/new?target=${encodeURIComponent(equipmentId)}`}
            className="mt-4 inline-flex rounded-xl bg-blue-500 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-400 focus:ring-2 focus:ring-cyan-300 focus:outline-none"
          >
            Підключити контролер →
          </Link>
        ) : null}
      </section>
    );
  }
  const snapshot = controller.latest;
  const value = (metric: string) => snapshot?.latestByMetric.get(metric);
  return (
    <div
      className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(340px,0.65fr)]"
      data-testid="refrigeration-controller-detail"
    >
      <section className="rounded-2xl border border-white/[0.08] bg-[#081a32] p-4 sm:p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-[10px] tracking-[0.16em] text-cyan-300 uppercase">Controller</p>
            <h2 className="mt-1 text-lg font-semibold text-white">Embraco Sync</h2>
          </div>
          <span
            className={`rounded-full border px-2.5 py-1 text-[10px] ${snapshot?.online ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-200" : "border-slate-400/20 bg-slate-400/10 text-slate-300"}`}
          >
            {snapshot?.online ? "● Online" : "○ Offline"}
          </span>
        </div>
        <dl className="mt-5 grid gap-x-6 gap-y-3 text-xs sm:grid-cols-2">
          <Info label="Node" value={binding.nodeId} />
          <Info label="Modbus Unit" value={String(binding.unitId)} />
          <Info label="Acquisition identity" value={binding.controllerEquipmentId} />
          <Info label="Profile" value={binding.profileVersion} />
          <Info label="Protocol" value="Modbus RTU · FC03 read-only" />
          <Info
            label="Last telemetry"
            value={snapshot?.lastSeenAt ? new Date(snapshot.lastSeenAt).toLocaleString("uk-UA") : "—"}
          />
        </dl>

        <div className="mt-6 border-t border-white/[0.07] pt-5">
          <div className="flex items-center gap-2">
            <ServerCog className="h-4 w-4 text-cyan-200" />
            <h3 className="text-sm font-semibold text-white">Поточні значення</h3>
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            <Current label="Cabinet" sample={value(EMBRACO_METRICS.cabinet)} />
            <Current label="Evaporator" sample={value(EMBRACO_METRICS.evaporator)} />
            <Current label="Condenser" sample={value(EMBRACO_METRICS.condenser)} />
            <Current label="Setpoint" sample={value(EMBRACO_METRICS.setpoint)} />
            <Current label="Hysteresis" sample={value(EMBRACO_METRICS.hysteresis)} />
            <Current label="Compressor" sample={value(EMBRACO_METRICS.compressorSpeed)} />
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-white/[0.08] bg-[#081a32] p-4 sm:p-5">
        <div className="flex items-center gap-2">
          <LockKeyhole className="h-4 w-4 text-amber-300" />
          <p className="text-[10px] tracking-[0.16em] text-amber-200 uppercase">Remote control locked</p>
        </div>
        <h2 className="mt-2 text-lg font-semibold text-white">Налаштування контролера</h2>
        <p className="mt-2 text-xs leading-5 text-slate-500">
          Setpoint і Hysteresis показуються лише для читання. Поточний профіль NEXOLAB не містить FC06/FC16 і
          не виконує Modbus write-команд.
        </p>
        <div className="mt-5 grid gap-3">
          <LockedSetting label="Setpoint" sample={value(EMBRACO_METRICS.setpoint)} />
          <LockedSetting label="Hysteresis" sample={value(EMBRACO_METRICS.hysteresis)} />
        </div>
        <div className="mt-5 rounded-xl border border-amber-400/15 bg-amber-400/[0.05] p-3 text-[10px] leading-4 text-amber-100/80">
          Керування буде окремим safety-gated Work Package після read-only acceptance. Старі або
          offline-команди не повинні виконуватися із черги.
        </div>
      </section>
    </div>
  );
}

function PanelMessage({ title, text, error = false }: { title: string; text: string; error?: boolean }) {
  return (
    <section
      role={error ? "alert" : undefined}
      className="rounded-2xl border border-white/[0.08] bg-[#081a32] p-8 text-center"
    >
      <RadioTower className="mx-auto h-6 w-6 text-slate-600" />
      <h2 className="mt-3 text-sm font-semibold text-white">{title}</h2>
      <p className="mt-2 text-xs text-slate-500">{text}</p>
    </section>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 border-b border-white/[0.05] pb-2">
      <dt className="text-[9px] tracking-[0.12em] text-slate-500 uppercase">{label}</dt>
      <dd className="mt-1 truncate font-medium text-slate-200" title={value}>
        {value}
      </dd>
    </div>
  );
}

function Current({
  label,
  sample,
}: {
  label: string;
  sample?: { value: number | null; unit: string; quality: string; raw_value: number | null };
}) {
  const valid = sample?.quality === "valid" && sample.value !== null && Number.isFinite(sample.value);
  return (
    <div className="rounded-xl border border-white/[0.07] bg-[#06142a]/70 px-3 py-3">
      <p className="text-[9px] tracking-[0.12em] text-slate-500 uppercase">{label}</p>
      <p className="mt-1 text-sm font-semibold text-white tabular-nums">
        {valid ? `${sample!.value} ${sample!.unit}` : "—"}
      </p>
      <p className="mt-1 text-[9px] text-slate-600">
        {sample?.quality === "unknown"
          ? `Raw ${sample.raw_value ?? "—"} · scale unverified`
          : (sample?.quality ?? "No data")}
      </p>
    </div>
  );
}

function LockedSetting({
  label,
  sample,
}: {
  label: string;
  sample?: { value: number | null; unit: string; quality: string; raw_value: number | null };
}) {
  const valid = sample?.quality === "valid" && sample.value !== null;
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-white/[0.07] bg-[#06142a]/70 px-3 py-3">
      <div>
        <p className="text-[9px] tracking-[0.12em] text-slate-500 uppercase">{label}</p>
        <p className="mt-1 text-sm font-semibold text-white">
          {valid ? `${sample!.value} ${sample!.unit}` : "—"}
        </p>
      </div>
      <LockKeyhole className="h-4 w-4 text-slate-600" />
    </div>
  );
}
