"use client";

import Link from "next/link";
import { AlertTriangle, Gauge, RadioTower, Snowflake, Thermometer } from "lucide-react";

import type { RefrigerationControllerModel } from "@/features/refrigeration/use-refrigeration-controller";
import { EMBRACO_METRICS } from "@/features/refrigeration/controller-monitoring";
import type { TelemetrySample } from "@/lib/telemetry/types";

export function RefrigerationControllerOverview({
  controller,
  equipmentId,
  canCommission,
}: {
  controller: RefrigerationControllerModel;
  equipmentId: string;
  canCommission: boolean;
}) {
  if (controller.bindingLoading)
    return <PanelMessage title="Контролер" text="Завантаження прив’язки контролера…" />;
  if (!controller.binding && controller.latestError)
    return <PanelMessage title="Контролер недоступний" text={controller.latestError} error />;
  if (!controller.binding) {
    return (
      <section className="rounded-2xl border border-white/[0.08] bg-[#081a32] p-8 text-center">
        <RadioTower className="mx-auto h-6 w-6 text-slate-600" />
        <h2 className="mt-3 text-sm font-semibold text-white">○ Контролер не підключено</h2>
        <p className="mt-2 text-xs text-slate-500">
          Створіть безпечну persistent-чернетку підключення для цієї вітрини.
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
  const metric = (name: string) => snapshot?.latestByMetric.get(name);
  const alarms = snapshot?.activeAlarms ?? null;

  return (
    <div className="grid gap-3 xl:gap-4" data-testid="refrigeration-controller-overview">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          icon={<Thermometer className="h-4 w-4" />}
          label="Cabinet"
          sample={metric(EMBRACO_METRICS.cabinet)}
        />
        <KpiCard
          icon={<Snowflake className="h-4 w-4" />}
          label="Evaporator"
          sample={metric(EMBRACO_METRICS.evaporator)}
        />
        <KpiCard
          icon={<Thermometer className="h-4 w-4" />}
          label="Condenser"
          sample={metric(EMBRACO_METRICS.condenser)}
        />
        <KpiCard
          icon={<Gauge className="h-4 w-4" />}
          label="Компресор"
          value={
            snapshot?.compressorSpeedRpm === null || snapshot?.compressorSpeedRpm === undefined
              ? "—"
              : `${Math.round(snapshot.compressorSpeedRpm)} rpm`
          }
          meta={
            snapshot?.compressorSpeedRpm && snapshot.compressorSpeedRpm > 0
              ? "Running"
              : "Stopped / unavailable"
          }
        />
      </div>

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.65fr)]">
        <section className="rounded-2xl border border-white/[0.08] bg-[#081a32] p-4 sm:p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-[10px] tracking-[0.16em] text-cyan-300 uppercase">Refrigeration state</p>
              <h2 className="mt-1 text-lg font-semibold text-white">Стан вітрини</h2>
            </div>
            <span
              className={`rounded-full border px-2.5 py-1 text-[10px] ${snapshot?.online ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-200" : "border-slate-400/20 bg-slate-400/10 text-slate-300"}`}
            >
              {snapshot?.online ? "● Embraco Online" : "○ Embraco Offline"}
            </span>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <StateTile label="Режим" value={snapshot?.controlState ?? "—"} />
            <StateTile
              label="Компресор"
              value={snapshot?.compressorSpeedRpm && snapshot.compressorSpeedRpm > 0 ? "ON" : "OFF / —"}
            />
            <StateTile
              label="Тривоги"
              value={alarms === null ? "—" : alarms.length === 0 ? "Немає" : String(alarms.length)}
            />
          </div>
          <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {(snapshot?.relayStates ?? [null, null, null, null]).map((state, index) => (
              <div key={index} className="rounded-xl border border-white/[0.07] bg-[#06142a]/70 px-3 py-2">
                <p className="text-[9px] tracking-[0.12em] text-slate-500 uppercase">Relay {index + 1}</p>
                <p className="mt-1 text-sm font-semibold text-slate-100">
                  {state === null ? "—" : state ? "ON" : "OFF"}
                </p>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-2xl border border-white/[0.08] bg-[#081a32] p-4 sm:p-5">
          <div className="flex items-center gap-2 text-cyan-200">
            <AlertTriangle className="h-4 w-4" />
            <p className="text-[10px] tracking-[0.16em] uppercase">Alarm state</p>
          </div>
          <h2 className="mt-2 text-lg font-semibold text-white">Активні тривоги</h2>
          {alarms === null ? (
            <p className="mt-4 text-xs leading-5 text-slate-500">Дані alarm bitfield ще недоступні.</p>
          ) : alarms.length === 0 ? (
            <p className="mt-4 rounded-xl border border-emerald-400/15 bg-emerald-400/[0.06] p-3 text-xs text-emerald-200">
              Активних тривог контролера немає.
            </p>
          ) : (
            <ul className="mt-4 grid gap-2 text-xs text-rose-200">
              {alarms.map((alarm) => (
                <li key={alarm} className="rounded-xl border border-rose-400/15 bg-rose-400/[0.06] p-3">
                  {alarm}
                </li>
              ))}
            </ul>
          )}
          {controller.latestError ? (
            <p role="alert" className="mt-3 text-[10px] leading-4 text-amber-300">
              {controller.latestError}
            </p>
          ) : null}
        </section>
      </div>
    </div>
  );
}

function KpiCard({
  icon,
  label,
  sample,
  value,
  meta,
}: {
  icon: React.ReactNode;
  label: string;
  sample?: TelemetrySample;
  value?: string;
  meta?: string;
}) {
  const valid = sample?.quality === "valid" && sample.value !== null && Number.isFinite(sample.value);
  const rendered = value ?? (valid ? `${sample!.value!.toFixed(1)} ${sample!.unit}` : "—");
  const detail =
    meta ?? (sample?.quality === "unknown" ? "Scale unverified" : sample ? sample.quality : "No data");
  return (
    <article className="rounded-2xl border border-white/[0.08] bg-[#081a32] p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="grid h-8 w-8 place-items-center rounded-xl border border-cyan-300/15 bg-cyan-400/[0.06] text-cyan-200">
          {icon}
        </span>
        <span className="text-[9px] text-slate-500">Live</span>
      </div>
      <p className="mt-4 text-[9px] tracking-[0.14em] text-slate-500 uppercase">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-white tabular-nums">{rendered}</p>
      <p className="mt-1 text-[10px] text-slate-500">{detail}</p>
    </article>
  );
}

function StateTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/[0.07] bg-[#06142a]/70 px-3 py-3">
      <p className="text-[9px] tracking-[0.12em] text-slate-500 uppercase">{label}</p>
      <p className="mt-1 text-sm font-semibold text-white">{value}</p>
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
