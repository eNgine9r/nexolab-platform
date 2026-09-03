"use client";

import Script from "next/script";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Clock3,
  Gauge,
  Snowflake,
  Thermometer,
  Zap,
} from "lucide-react";

const TELEGRAM_SDK = "https://telegram.org/js/telegram-web-app.js?63";
const SNAPSHOT_SCHEMA = "refrigeration-daily-report/v1";

type RecordValue = Record<string, unknown>;

type Snapshot = {
  id: string;
  localReportDate: string;
  scheduledFor: string;
  windowStart: string;
  windowEnd: string;
  timezone: string;
  status: string;
  payload: RecordValue;
};

type TelegramWebApp = {
  initData?: string;
  ready?: () => void;
  expand?: () => void;
  setHeaderColor?: (color: string) => void;
  setBackgroundColor?: (color: string) => void;
};

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}

const STATUS: Record<string, { label: string; classes: string }> = {
  normal: { label: "Норма", classes: "border-emerald-400/25 bg-emerald-400/10 text-emerald-200" },
  attention: { label: "Увага", classes: "border-amber-300/25 bg-amber-300/10 text-amber-100" },
  critical: { label: "Критично", classes: "border-red-400/30 bg-red-400/10 text-red-100" },
  incomplete: { label: "Неповні дані", classes: "border-slate-400/20 bg-slate-400/10 text-slate-200" },
};

const QUALITY_REASON_LABELS: Record<string, string> = {
  m_packet_coverage_incomplete: "Не всі M-пакети мають валідні актуальні дані",
  controller_not_bound: "Контролер не прив’язаний",
  controller_state_unavailable: "Стан контролера недоступний",
  compressor_evidence_unavailable: "Дані компресора недоступні",
  compressor_coverage_incomplete: "Покриття компресора неповне",
  defrost_evidence_unavailable: "Дані відтайки недоступні",
  defrost_coverage_incomplete: "Покриття відтайки неповне",
  energy_evidence_unavailable: "Енергетичні межі недоступні",
  alert_history_truncated: "Історія тривог обмежена",
};

function asRecord(value: unknown): RecordValue {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as RecordValue) : {};
}

function finite(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return value;
}

function integer(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function validateSnapshot(value: unknown): Snapshot | null {
  const envelope = asRecord(value);
  const report = asRecord(envelope.report);
  const payload = asRecord(report.payload);
  if (payload.schema !== SNAPSHOT_SCHEMA) return null;
  const id = text(report.id);
  const localReportDate = text(report.local_report_date);
  const scheduledFor = text(report.scheduled_for);
  const windowStart = text(report.window_start);
  const windowEnd = text(report.window_end);
  const timezone = text(report.timezone);
  const status = text(report.status);
  if (!id || !localReportDate || !scheduledFor || !windowStart || !windowEnd || !timezone || !status) {
    return null;
  }
  if ([scheduledFor, windowStart, windowEnd].some((item) => Number.isNaN(Date.parse(item)))) return null;
  return { id, localReportDate, scheduledFor, windowStart, windowEnd, timezone, status, payload };
}

function localDateTime(value: string, timezone: string): string {
  try {
    return new Intl.DateTimeFormat("uk-UA", {
      timeZone: timezone,
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(value));
  } catch {
    return "Недоступно";
  }
}

function temperature(value: unknown): string {
  const number = finite(value);
  return number === null ? "Недоступно" : `${number.toFixed(1)} °C`;
}

function percent(value: unknown): string {
  const number = finite(value);
  return number === null ? "Недоступно" : `${number.toFixed(1)} %`;
}

function energy(value: unknown): string {
  const number = finite(value);
  return number === null ? "Недоступно" : `${number.toFixed(2)} kWh`;
}

function duration(value: unknown): string {
  const seconds = finite(value);
  if (seconds === null || seconds < 0) return "Недоступно";
  const minutes = seconds / 60;
  return Number.isInteger(minutes) ? `${minutes} хв` : `${minutes.toFixed(1)} хв`;
}

function metricUnavailable(value: unknown): string {
  const section = asRecord(value);
  if (section.status !== "available") return "Недоступно";
  for (const key of ["value", "value_c", "temperature_c", "value_k", "delta_k"]) {
    const number = finite(section[key]);
    if (number !== null) return number.toFixed(1);
  }
  return "Недоступно";
}

function ErrorState({ message }: { message: string }) {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-[480px] items-center px-5 py-10">
      <div className="panel w-full p-6 text-center">
        <AlertTriangle className="mx-auto mb-4 h-8 w-8 text-amber-300" aria-hidden="true" />
        <h1 className="text-lg font-semibold text-slate-100">NEXOLAB Mini App</h1>
        <p className="mt-3 text-sm leading-6 text-slate-400">{message}</p>
      </div>
    </main>
  );
}

export function TelegramMiniAppReport() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const requested = useRef(false);

  const loadReport = useCallback(async () => {
    if (requested.current) return;
    const webApp = window.Telegram?.WebApp;
    if (!webApp) {
      setError("Відкрийте цей звіт через кнопку в Telegram. Telegram-контекст не знайдено.");
      return;
    }
    const initData = webApp.initData?.trim();
    if (!initData) {
      requested.current = true;
      setError("Telegram не передав підтверджені дані авторизації. Доступ закрито.");
      return;
    }
    requested.current = true;
    webApp.ready?.();
    webApp.expand?.();
    webApp.setHeaderColor?.("#06142a");
    webApp.setBackgroundColor?.("#06142a");

    const candidateHint = new URLSearchParams(window.location.search).get("tgWebAppStartParam")?.trim();
    const startHint = candidateHint && candidateHint.length <= 128 ? candidateHint : undefined;
    try {
      const response = await fetch("/api/telegram-miniapp/report", {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ init_data: initData, ...(startHint ? { start_hint: startHint } : {}) }),
        cache: "no-store",
      });
      const value: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        const code = text(asRecord(asRecord(value).detail).code);
        if (response.status === 401) {
          throw new Error("Telegram-сесія недійсна або прострочена. Відкрийте звіт із повідомлення ще раз.");
        }
        if (response.status === 403) {
          throw new Error("Ваш Telegram-користувач не має дозволеного зв’язку з NEXOLAB.");
        }
        if (response.status === 404) {
          throw new Error("Збережений звіт не знайдено або він недоступний у вашій організації.");
        }
        throw new Error(code ? `Mini App тимчасово недоступний (${code}).` : "Mini App тимчасово недоступний.");
      }
      const parsed = validateSnapshot(value);
      if (!parsed) throw new Error("NEXOLAB повернув некоректний формат збереженого звіту.");
      setSnapshot(parsed);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не вдалося завантажити збережений звіт.");
    }
  }, []);

  useEffect(() => {
    if (window.Telegram?.WebApp) void loadReport();
  }, [loadReport]);

  if (error) {
    return (
      <>
        <Script src={TELEGRAM_SDK} strategy="afterInteractive" onReady={() => void loadReport()} />
        <ErrorState message={error} />
      </>
    );
  }

  if (!snapshot) {
    return (
      <>
        <Script
          src={TELEGRAM_SDK}
          strategy="afterInteractive"
          onReady={() => void loadReport()}
          onError={() => setError("Не вдалося завантажити офіційний Telegram Mini App SDK.")}
        />
        <main className="mx-auto flex min-h-dvh w-full max-w-[480px] items-center px-5 py-10">
          <div className="panel w-full p-6 text-center">
            <Snowflake className="mx-auto h-9 w-9 animate-pulse text-cyan-300" aria-hidden="true" />
            <p className="mt-4 text-sm text-slate-300">Відкриваємо збережений ранковий звіт…</p>
          </div>
        </main>
      </>
    );
  }

  const identity = asRecord(snapshot.payload.identity);
  const report = asRecord(snapshot.payload.report);
  const mPackets = asRecord(snapshot.payload.m_packets);
  const circuit = asRecord(snapshot.payload.refrigeration_circuit);
  const compressor = asRecord(snapshot.payload.compressor);
  const energySection = asRecord(snapshot.payload.energy);
  const defrost = asRecord(snapshot.payload.defrost);
  const alerts = asRecord(snapshot.payload.alerts);
  const quality = asRecord(snapshot.payload.quality);
  const status = STATUS[text(report.status) || snapshot.status] || STATUS.incomplete;
  const channels = Array.isArray(mPackets.channels) ? mPackets.channels.map(asRecord) : [];
  const alertItems = Array.isArray(alerts.items) ? alerts.items.map(asRecord).slice(0, 8) : [];
  const qualityReasons = Array.isArray(quality.reasons)
    ? quality.reasons.filter((item): item is string => typeof item === "string")
    : [];
  const equipmentName = text(identity.equipment_name) || text(identity.equipment_code) || "Обладнання";
  const equipmentSubtitle = [text(identity.manufacturer), text(identity.model)].filter(Boolean).join(" · ");
  const validChannels = integer(mPackets.valid_channels);
  const configuredChannels = integer(mPackets.configured_channels);
  const activeAlerts = integer(alerts.active_count);
  const recentAlerts = integer(alerts.recent_count);

  return (
    <>
      <Script src={TELEGRAM_SDK} strategy="afterInteractive" />
      <main className="mx-auto min-h-dvh w-full max-w-[480px] px-4 pb-[calc(1.5rem+env(safe-area-inset-bottom))] pt-[calc(1rem+env(safe-area-inset-top))] text-slate-100">
        <header className="mb-4 rounded-2xl border border-cyan-300/10 bg-[#081d39]/90 p-4 shadow-2xl shadow-black/20">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">
                <Snowflake className="h-4 w-4" aria-hidden="true" /> NEXOLAB
              </div>
              <h1 className="mt-2 text-xl font-semibold leading-tight">{equipmentName}</h1>
              {equipmentSubtitle ? <p className="mt-1 text-xs text-slate-400">{equipmentSubtitle}</p> : null}
            </div>
            <span className={`rounded-full border px-3 py-1.5 text-xs font-semibold ${status.classes}`}>
              {status.label}
            </span>
          </div>
          <div className="mt-4 flex items-center gap-2 rounded-xl border border-slate-400/10 bg-black/10 px-3 py-2 text-xs text-slate-400">
            <Clock3 className="h-4 w-4 text-cyan-300" aria-hidden="true" />
            <span>Збережений звіт · не live · {snapshot.localReportDate}</span>
          </div>
          <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
            <div className="rounded-xl bg-white/[0.025] p-3">
              <dt className="text-slate-500">Початок вікна</dt>
              <dd className="mt-1 font-medium text-slate-200">{localDateTime(snapshot.windowStart, snapshot.timezone)}</dd>
            </div>
            <div className="rounded-xl bg-white/[0.025] p-3">
              <dt className="text-slate-500">Кінець вікна</dt>
              <dd className="mt-1 font-medium text-slate-200">{localDateTime(snapshot.windowEnd, snapshot.timezone)}</dd>
            </div>
          </dl>
          <p className="mt-3 text-xs text-slate-500">Холодоагент: Недоступно в поточному профілі даних</p>
        </header>

        <nav aria-label="Деталі звіту" className="mb-4 grid grid-cols-3 gap-2 text-center text-xs">
          <a href="#m-packets" className="rounded-xl border border-slate-400/10 bg-white/[0.025] px-2 py-2 text-slate-300">M-пакети</a>
          <a href="#circuit" className="rounded-xl border border-slate-400/10 bg-white/[0.025] px-2 py-2 text-slate-300">Контур</a>
          <a href="#alerts" className="rounded-xl border border-slate-400/10 bg-white/[0.025] px-2 py-2 text-slate-300">Тривоги</a>
        </nav>

        <section id="m-packets" className="panel mb-4 p-4">
          <div className="flex items-center gap-2 text-sm font-semibold"><Thermometer className="h-4 w-4 text-cyan-300" aria-hidden="true" /> M-пакети</div>
          <div className="mt-3 grid grid-cols-3 gap-2">
            <Metric label="Tmin" value={temperature(mPackets.minimum_c)} />
            <Metric label="Tmax" value={temperature(mPackets.maximum_c)} />
            <Metric label="Валідні" value={validChannels !== null && configuredChannels !== null ? `${validChannels}/${configuredChannels}` : "Недоступно"} />
          </div>
          <details className="mt-3 rounded-xl border border-slate-400/10 bg-black/10 p-3">
            <summary className="cursor-pointer text-xs font-medium text-slate-300">Показати канали ({channels.length})</summary>
            <div className="mt-3 space-y-2">
              {channels.length ? channels.map((channel, index) => (
                <div key={`${text(channel.channel_id) || "channel"}-${index}`} className="flex items-center justify-between gap-3 rounded-lg bg-white/[0.025] px-3 py-2 text-xs">
                  <span className="min-w-0 truncate text-slate-400">{text(channel.label) || text(channel.channel_id) || `Канал ${index + 1}`}</span>
                  <span className="shrink-0 font-medium text-slate-200">{channel.status === "available" ? temperature(channel.value_c) : "Недоступно"}</span>
                </div>
              )) : <p className="text-xs text-slate-500">Канали недоступні.</p>}
            </div>
          </details>
        </section>

        <section id="circuit" className="panel mb-4 p-4">
          <div className="flex items-center gap-2 text-sm font-semibold"><Snowflake className="h-4 w-4 text-cyan-300" aria-hidden="true" /> Холодильний контур</div>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <Metric label="Кипіння" value={metricUnavailable(circuit.evaporation_saturation_temperature)} />
            <Metric label="Перегрів" value={metricUnavailable(circuit.superheat)} />
            <Metric label="Конденсація" value={metricUnavailable(circuit.condensation_saturation_temperature)} />
            <Metric label="Переохолодження" value={metricUnavailable(circuit.subcooling)} />
          </div>
          <p className="mt-3 text-xs leading-5 text-slate-500">Термодинамічні показники не обчислюються в Mini App і залишаються недоступними до окремої hardware-accepted реалізації.</p>
        </section>

        <section className="mb-4 grid grid-cols-2 gap-3">
          <KpiPanel icon={<Gauge className="h-4 w-4 text-cyan-300" />} title="Компресор" primary={compressor.status === "available" ? percent(compressor.duty_percent) : "Недоступно"} secondary={`Покриття: ${compressor.status === "available" ? percent(compressor.coverage_percent) : "Недоступно"}`} />
          <KpiPanel icon={<Zap className="h-4 w-4 text-amber-300" />} title="Енергія" primary={energySection.status === "available" ? energy(energySection.interval_kwh) : "Недоступно"} secondary="За вікно звіту" />
          <KpiPanel icon={<Snowflake className="h-4 w-4 text-blue-300" />} title="Відтайка" primary={defrost.status === "available" ? duration(defrost.duration_seconds) : "Недоступно"} secondary="Тільки тривалість" />
          <KpiPanel icon={<BarChart3 className="h-4 w-4 text-emerald-300" />} title="Якість" primary={quality.status === "complete" ? "Повні дані" : "Неповні дані"} secondary={`${qualityReasons.length} зауважень`} />
        </section>

        <section id="alerts" className="panel mb-4 p-4">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm font-semibold"><AlertTriangle className="h-4 w-4 text-amber-300" aria-hidden="true" /> Тривоги</div>
            <span className="text-xs text-slate-500">активні {activeAlerts ?? "—"} · за вікно {recentAlerts ?? "—"}</span>
          </div>
          <div className="mt-3 space-y-2">
            {alertItems.length ? alertItems.map((item, index) => (
              <div key={text(item.id) || `alert-${index}`} className="rounded-xl border border-slate-400/10 bg-white/[0.025] px-3 py-2 text-xs">
                <div className="flex justify-between gap-3">
                  <span className="font-medium text-slate-200">{text(item.severity) || "warning"}</span>
                  <span className="text-slate-500">{text(item.state) || "unknown"}</span>
                </div>
                <p className="mt-1 truncate text-slate-500">{text(item.metric) || text(item.channel_id) || text(item.equipment_id) || "Подія NEXOLAB"}</p>
              </div>
            )) : (
              <div className="flex items-center gap-2 rounded-xl bg-emerald-400/[0.06] px-3 py-3 text-xs text-emerald-200">
                <CheckCircle2 className="h-4 w-4" aria-hidden="true" /> Активних або недавніх тривог у збереженому вікні немає.
              </div>
            )}
          </div>
        </section>

        {qualityReasons.length ? (
          <section className="rounded-2xl border border-amber-300/15 bg-amber-300/[0.05] p-4">
            <h2 className="text-sm font-semibold text-amber-100">Якість та покриття</h2>
            <ul className="mt-2 space-y-1.5 text-xs leading-5 text-amber-100/70">
              {qualityReasons.map((reason) => <li key={reason}>• {QUALITY_REASON_LABELS[reason] || reason}</li>)}
            </ul>
          </section>
        ) : null}

        <footer className="px-2 pb-2 pt-5 text-center text-[11px] leading-5 text-slate-600">
          Дані лише для читання. Авторитет — збережений NEXOLAB snapshot {snapshot.id.slice(0, 8)}…
        </footer>
      </main>
    </>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-400/10 bg-white/[0.025] p-3">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-sm font-semibold text-slate-100">{value}</div>
    </div>
  );
}

function KpiPanel({ icon, title, primary, secondary }: { icon: React.ReactNode; title: string; primary: string; secondary: string }) {
  return (
    <div className="panel p-4">
      <div className="flex items-center gap-2 text-xs text-slate-400">{icon}{title}</div>
      <div className="mt-2 text-lg font-semibold text-slate-100">{primary}</div>
      <div className="mt-1 text-[11px] text-slate-500">{secondary}</div>
    </div>
  );
}
