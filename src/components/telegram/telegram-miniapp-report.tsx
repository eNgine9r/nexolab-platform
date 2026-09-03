"use client";

import Script from "next/script";
import {
  AlertTriangle,
  BarChart3,
  Bolt,
  Clock3,
  Gauge,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
  Snowflake,
  ThermometerSnowflake,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

type JsonRecord = Record<string, unknown>;

type TelegramWebApp = {
  initData: string;
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

type LoadState =
  | { kind: "loading" }
  | { kind: "outside_telegram" }
  | { kind: "denied" }
  | { kind: "unavailable" }
  | { kind: "invalid" }
  | { kind: "ready"; snapshot: JsonRecord };

const STATUS = {
  normal: { label: "Норма", className: "border-emerald-400/25 bg-emerald-400/10 text-emerald-200" },
  attention: { label: "Увага", className: "border-amber-400/25 bg-amber-400/10 text-amber-100" },
  critical: { label: "Критично", className: "border-red-400/30 bg-red-400/10 text-red-100" },
  incomplete: { label: "Неповні дані", className: "border-slate-400/20 bg-slate-300/5 text-slate-200" },
} as const;

export function TelegramMiniAppReport() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const started = useRef(false);

  const load = useCallback(async () => {
    if (started.current) return;
    const webApp = window.Telegram?.WebApp;
    if (!webApp) return;
    started.current = true;
    webApp.ready?.();
    webApp.expand?.();
    webApp.setHeaderColor?.("#06142a");
    webApp.setBackgroundColor?.("#06142a");

    const initData = webApp.initData?.trim();
    if (!initData) {
      setState({ kind: "outside_telegram" });
      return;
    }
    const startHint = new URLSearchParams(initData).get("start_param")?.trim() || undefined;
    try {
      const response = await fetch("/api/telegram-miniapp/report", {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ init_data: initData, ...(startHint ? { start_hint: startHint } : {}) }),
        cache: "no-store",
      });
      const payload: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        if (response.status === 401 || response.status === 403) setState({ kind: "denied" });
        else setState({ kind: "unavailable" });
        return;
      }
      const snapshot = readSnapshotEnvelope(payload);
      setState(snapshot ? { kind: "ready", snapshot } : { kind: "invalid" });
    } catch {
      setState({ kind: "unavailable" });
    }
  }, []);

  useEffect(() => {
    if (window.Telegram?.WebApp) void load();
  }, [load]);

  return (
    <main className="min-h-dvh bg-[#06142a] px-3 pb-10 pt-3 text-slate-100 sm:px-5">
      <Script
        id="telegram-web-app-sdk"
        src="https://telegram.org/js/telegram-web-app.js"
        strategy="afterInteractive"
        onReady={() => void load()}
        onError={() => setState((current) => (current.kind === "loading" ? { kind: "unavailable" } : current))}
      />
      <div className="mx-auto w-full max-w-xl">
        <MiniAppHeader />
        {state.kind === "ready" ? <ReportView snapshot={state.snapshot} /> : <LoadPanel state={state.kind} />}
      </div>
    </main>
  );
}

function MiniAppHeader() {
  return (
    <header className="mb-3 flex items-center justify-between rounded-2xl border border-cyan-300/10 bg-[#0a1f3d]/90 px-4 py-3 shadow-2xl shadow-black/20">
      <div className="flex items-center gap-3">
        <div className="grid size-10 place-items-center rounded-xl border border-cyan-300/15 bg-cyan-300/5 text-cyan-200">
          <Snowflake className="size-5" aria-hidden="true" />
        </div>
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-cyan-200/70">NEXOLAB</p>
          <h1 className="text-sm font-semibold text-white">Ранковий звіт</h1>
        </div>
      </div>
      <span className="rounded-full border border-slate-400/15 bg-slate-200/5 px-2.5 py-1 text-[10px] font-medium text-slate-300">
        READ ONLY
      </span>
    </header>
  );
}

function LoadPanel({ state }: { state: Exclude<LoadState["kind"], "ready"> }) {
  const content = {
    loading: ["Перевіряємо доступ", "Telegram підтверджує підпис і прив’язку користувача."],
    outside_telegram: ["Відкрийте звіт через Telegram", "Ця сторінка приймає лише підписаний Telegram Mini App сеанс."],
    denied: ["Доступ не підтверджено", "Telegram-користувач не прив’язаний до дозволеного NEXOLAB облікового запису або не має права читати звіти."],
    unavailable: ["Mini App тимчасово недоступний", "Перевірте з’єднання та повторіть відкриття звіту з повідомлення Telegram."],
    invalid: ["Некоректний формат звіту", "NEXOLAB відхилив відповідь, яка не відповідає persisted morning-report contract."],
  }[state];
  return (
    <section className="panel px-5 py-8 text-center">
      <div className="mx-auto mb-4 grid size-12 place-items-center rounded-2xl border border-cyan-300/10 bg-cyan-300/5 text-cyan-100">
        {state === "loading" ? <RefreshCw className="size-5 animate-spin" /> : <LockKeyhole className="size-5" />}
      </div>
      <h2 className="text-base font-semibold text-white">{content[0]}</h2>
      <p className="mx-auto mt-2 max-w-sm text-xs leading-5 text-slate-400">{content[1]}</p>
    </section>
  );
}

function ReportView({ snapshot }: { snapshot: JsonRecord }) {
  const payload = record(snapshot.payload);
  const report = record(payload.report);
  const identity = record(payload.identity);
  const packets = record(payload.m_packets);
  const circuit = record(payload.refrigeration_circuit);
  const compressor = record(payload.compressor);
  const energy = record(payload.energy);
  const defrost = record(payload.defrost);
  const alerts = record(payload.alerts);
  const quality = record(payload.quality);
  const statusKey = text(report.status) ?? text(snapshot.status) ?? "incomplete";
  const status = STATUS[statusKey as keyof typeof STATUS] ?? STATUS.incomplete;
  const equipment = text(identity.equipment_name) ?? text(identity.equipment_code) ?? "Обладнання не вказано";
  const equipmentMeta = [text(identity.manufacturer), text(identity.model)].filter(Boolean).join(" · ");
  const refrigerant = text(identity.refrigerant);
  const timezone = text(report.timezone) ?? text(snapshot.timezone) ?? "Europe/Kyiv";
  const windowStart = text(report.window_start) ?? text(snapshot.window_start);
  const windowEnd = text(report.window_end) ?? text(snapshot.window_end);
  const scheduledFor = text(report.scheduled_for) ?? text(snapshot.scheduled_for);
  const localDate = text(report.local_report_date) ?? text(snapshot.local_report_date);
  const channels = array(packets.channels).filter(isRecord);
  const alertItems = array(alerts.items).filter(isRecord);
  const qualityReasons = array(quality.reasons).filter((item): item is string => typeof item === "string");
  const analysisMinutes = integer(report.analysis_window_minutes);
  const analysisLabel = analysisMinutes ? `${formatHours(analysisMinutes)} · persisted KPI` : "persisted KPI";

  return (
    <div className="space-y-3">
      <section className="panel p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Збережений звіт · не live</p>
            <h2 className="mt-1 truncate text-lg font-semibold text-white">{equipment}</h2>
            {equipmentMeta ? <p className="mt-1 text-xs text-slate-400">{equipmentMeta}</p> : null}
            {refrigerant ? <p className="mt-1 text-xs text-slate-400">Холодоагент: {refrigerant}</p> : null}
          </div>
          <span className={`shrink-0 rounded-full border px-3 py-1.5 text-xs font-semibold ${status.className}`}>{status.label}</span>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
          <InfoCell label="Дата звіту" value={formatDate(localDate, timezone)} icon={<Clock3 className="size-4" />} />
          <InfoCell label="Сформовано" value={formatDateTime(scheduledFor, timezone)} icon={<ShieldCheck className="size-4" />} />
        </div>
        <div className="mt-2 rounded-xl border border-slate-400/10 bg-black/10 px-3 py-2.5">
          <p className="text-[10px] uppercase tracking-[0.12em] text-slate-500">Вікно даних · {timezone}</p>
          <p className="mt-1 text-xs font-medium text-slate-200">{formatDateTime(windowStart, timezone)} → {formatDateTime(windowEnd, timezone)}</p>
        </div>
      </section>

      {quality.status === "incomplete" || qualityReasons.length ? <QualityWarning reasons={qualityReasons} /> : null}

      <nav className="flex gap-2 overflow-x-auto pb-1 text-[11px] scrollbar-thin" aria-label="Розділи звіту">
        {[["#m-packets", "М-пакети"], ["#summary", "Показники"], ["#circuit", "Контур"], ["#alerts", "Тривоги"]].map(([href, label]) => (
          <a key={href} href={href} className="shrink-0 rounded-full border border-slate-400/10 bg-white/[0.025] px-3 py-1.5 text-slate-300">{label}</a>
        ))}
      </nav>

      <section id="m-packets" className="panel p-4 scroll-mt-3">
        <SectionTitle icon={<ThermometerSnowflake className="size-4" />} title="М-пакети" subtitle={`${integer(packets.valid_channels) ?? 0} / ${integer(packets.configured_channels) ?? "—"} валідних`} />
        <div className="mt-3 grid grid-cols-2 gap-2">
          <MetricCard label="Tmin" value={temperature(packets.minimum_c)} />
          <MetricCard label="Tmax" value={temperature(packets.maximum_c)} />
        </div>
        <div className="mt-3 space-y-2">
          {channels.length ? channels.map((channel, index) => <ChannelRow key={`${text(channel.channel_id) ?? "channel"}-${index}`} channel={channel} timezone={timezone} />) : <UnavailableRow text="Список M-пакетів недоступний у цьому snapshot." />}
        </div>
      </section>

      <section id="summary" className="panel p-4 scroll-mt-3">
        <SectionTitle icon={<BarChart3 className="size-4" />} title="Підсумок за вікно" subtitle={analysisLabel} />
        <div className="mt-3 grid grid-cols-2 gap-2">
          <MetricCard icon={<Gauge className="size-4" />} label="Компресор" value={percent(compressor.duty_percent, compressor.status)} subvalue={coverage(compressor.coverage_percent)} />
          <MetricCard icon={<Bolt className="size-4" />} label="Енергія" value={energyValue(energy)} subvalue={energy.status === "available" ? "за вікно звіту" : "недоступно"} />
          <MetricCard icon={<RefreshCw className="size-4" />} label="Відтайка" value={duration(defrost)} subvalue="тільки тривалість" />
          <MetricCard icon={<AlertTriangle className="size-4" />} label="Тривоги" value={`${integer(alerts.active_count) ?? 0} активних`} subvalue={`${integer(alerts.recent_count) ?? 0} у вікні`} />
        </div>
      </section>

      <section id="circuit" className="panel p-4 scroll-mt-3">
        <SectionTitle icon={<Snowflake className="size-4" />} title="Холодильний контур" subtitle="непідтверджені RFX-метрики не обчислюються" />
        <div className="mt-3 grid grid-cols-2 gap-2">
          <MetricCard label="Кипіння" value={derivedMetric(circuit.evaporation_saturation_temperature, "°C")} />
          <MetricCard label="Перегрів" value={derivedMetric(circuit.superheat, "K")} />
          <MetricCard label="Конденсація" value={derivedMetric(circuit.condensation_saturation_temperature, "°C")} />
          <MetricCard label="Переохолодження" value={derivedMetric(circuit.subcooling, "K")} />
        </div>
      </section>

      <section id="alerts" className="panel p-4 scroll-mt-3">
        <SectionTitle icon={<AlertTriangle className="size-4" />} title="Тривоги" subtitle={`${integer(alerts.active_count) ?? 0} активних · ${integer(alerts.recent_count) ?? 0} у вікні`} />
        <div className="mt-3 space-y-2">
          {alertItems.length ? alertItems.slice(0, 12).map((item, index) => <AlertRow key={`${text(item.id) ?? "alert"}-${index}`} item={item} timezone={timezone} />) : <UnavailableRow text="Активних або недавніх тривог у вікні звіту немає." />}
        </div>
      </section>

      <footer className="px-2 pt-1 text-center text-[10px] leading-4 text-slate-500">
        NEXOLAB Mini App показує persisted snapshot. Керування обладнанням, підтвердження тривог і адміністративні дії відсутні.
      </footer>
    </div>
  );
}

function InfoCell({ label, value, icon }: { label: string; value: string; icon: React.ReactNode }) {
  return <div className="rounded-xl border border-slate-400/10 bg-white/[0.025] p-3"><div className="flex items-center gap-2 text-cyan-200">{icon}<span className="text-[10px] uppercase tracking-[0.1em] text-slate-500">{label}</span></div><p className="mt-1.5 font-medium text-slate-200">{value}</p></div>;
}

function SectionTitle({ icon, title, subtitle }: { icon: React.ReactNode; title: string; subtitle?: string }) {
  return <div className="flex items-start gap-2.5"><div className="mt-0.5 text-cyan-200">{icon}</div><div><h3 className="text-sm font-semibold text-white">{title}</h3>{subtitle ? <p className="mt-0.5 text-[10px] leading-4 text-slate-500">{subtitle}</p> : null}</div></div>;
}

function MetricCard({ label, value, subvalue, icon }: { label: string; value: string; subvalue?: string; icon?: React.ReactNode }) {
  return <div className="rounded-xl border border-slate-400/10 bg-white/[0.025] p-3"><div className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.1em] text-slate-500">{icon ? <span className="text-cyan-200">{icon}</span> : null}{label}</div><p className="mt-1.5 text-base font-semibold text-white">{value}</p>{subvalue ? <p className="mt-1 text-[10px] text-slate-500">{subvalue}</p> : null}</div>;
}

function ChannelRow({ channel, timezone }: { channel: JsonRecord; timezone: string }) {
  const available = channel.status === "available" && finite(channel.value_c) !== null;
  return <div className="flex items-center justify-between gap-3 rounded-xl border border-slate-400/10 bg-black/10 px-3 py-2.5"><div className="min-w-0"><p className="truncate text-xs font-medium text-slate-200">{text(channel.label) ?? text(channel.channel_id) ?? "M-пакет"}</p><p className="mt-0.5 truncate text-[10px] text-slate-500">{available ? formatDateTime(text(channel.captured_at), timezone) : unavailableReason(text(channel.reason))}</p></div><div className="text-right"><p className={`text-sm font-semibold ${available ? "text-white" : "text-slate-500"}`}>{available ? temperature(channel.value_c) : "Недоступно"}</p><p className={`mt-0.5 text-[9px] uppercase tracking-[0.08em] ${available ? "text-emerald-300/80" : "text-slate-600"}`}>{available ? "valid" : "unavailable"}</p></div></div>;
}

function AlertRow({ item, timezone }: { item: JsonRecord; timezone: string }) {
  const severity = text(item.severity) ?? "unknown";
  const severityClass = severity === "critical" ? "text-red-200" : severity === "warning" ? "text-amber-200" : "text-slate-300";
  return <div className="rounded-xl border border-slate-400/10 bg-black/10 px-3 py-2.5"><div className="flex items-center justify-between gap-2"><p className={`text-[10px] font-semibold uppercase tracking-[0.1em] ${severityClass}`}>{severityLabel(severity)}</p><span className="text-[10px] text-slate-500">{formatDateTime(text(item.triggered_at), timezone)}</span></div><p className="mt-1 truncate text-xs text-slate-300">{text(item.channel_id) ?? text(item.equipment_id) ?? "Обладнання"} · {text(item.metric) ?? "Тривога"}</p></div>;
}

function QualityWarning({ reasons }: { reasons: string[] }) {
  return <section className="rounded-2xl border border-amber-300/20 bg-amber-300/[0.06] px-4 py-3"><div className="flex gap-2.5"><AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-200" /><div><p className="text-xs font-semibold text-amber-100">Неповні дані</p><p className="mt-1 text-[11px] leading-4 text-amber-100/65">{reasons.length ? reasons.map(qualityReason).join(" · ") : "Частина evidence у вікні звіту недоступна."}</p></div></div></section>;
}

function UnavailableRow({ text: value }: { text: string }) {
  return <div className="rounded-xl border border-dashed border-slate-400/10 px-3 py-3 text-center text-[11px] text-slate-500">{value}</div>;
}

function readSnapshotEnvelope(value: unknown): JsonRecord | null {
  if (!isRecord(value) || !isRecord(value.report)) return null;
  const snapshot = value.report;
  if (!text(snapshot.id) || !isRecord(snapshot.payload)) return null;
  const payload = snapshot.payload;
  if (payload.schema !== "refrigeration-daily-report/v1" || !isRecord(payload.report) || !isRecord(payload.identity)) return null;
  return snapshot;
}

function record(value: unknown): JsonRecord { return isRecord(value) ? value : {}; }
function isRecord(value: unknown): value is JsonRecord { return typeof value === "object" && value !== null && !Array.isArray(value); }
function array(value: unknown): unknown[] { return Array.isArray(value) ? value : []; }
function text(value: unknown): string | null { return typeof value === "string" && value.trim() ? value.trim() : null; }
function integer(value: unknown): number | null { return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null; }
function finite(value: unknown): number | null { return typeof value === "number" && Number.isFinite(value) ? value : null; }
function temperature(value: unknown): string { const n = finite(value); return n === null ? "Недоступно" : `${n.toFixed(1)} °C`; }
function coverage(value: unknown): string { const n = finite(value); return n === null ? "coverage недоступний" : `coverage ${n.toFixed(1)} %`; }
function percent(value: unknown, status: unknown): string { const n = finite(value); return status !== "available" || n === null ? "Недоступно" : `${n.toFixed(1)} %`; }
function energyValue(section: JsonRecord): string { const n = finite(section.interval_kwh); return section.status !== "available" || n === null ? "Недоступно" : `${n.toFixed(2)} kWh`; }
function duration(section: JsonRecord): string { const seconds = finite(section.duration_seconds); if (section.status !== "available" || seconds === null || seconds < 0) return "Недоступно"; const minutes = seconds / 60; return Number.isInteger(minutes) ? `${minutes} хв` : `${minutes.toFixed(1)} хв`; }
function derivedMetric(value: unknown, unit: string): string { const section = record(value); if (section.status !== "available") return "Недоступно"; const n = finite(section.value) ?? finite(section.value_c) ?? finite(section.temperature_c) ?? finite(section.value_k) ?? finite(section.delta_k); return n === null ? "Недоступно" : `${n.toFixed(1)} ${text(section.unit) ?? unit}`; }
function unavailableReason(reason: string | null): string { return ({ no_data: "немає даних", stale: "застарілі дані", invalid_quality: "невалідна якість" } as Record<string, string>)[reason ?? ""] ?? "дані недоступні"; }
function severityLabel(value: string): string { return ({ critical: "Критично", warning: "Увага", info: "Інформація" } as Record<string, string>)[value] ?? "Тривога"; }
function qualityReason(value: string): string { return ({ m_packet_coverage_incomplete: "неповне покриття M-пакетів", compressor_coverage_incomplete: "неповне покриття компресора", energy_evidence_unavailable: "energy evidence недоступний", defrost_evidence_unavailable: "відтайка недоступна", defrost_coverage_incomplete: "неповне покриття відтайки" } as Record<string, string>)[value] ?? "частина evidence недоступна"; }
function formatDate(value: string | null, _timezone: string): string { if (!value) return "—"; const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value); return match ? `${match[3]}.${match[2]}.${match[1]}` : value; }
function formatHours(minutes: number): string { const hours = minutes / 60; return `${Number.isInteger(hours) ? hours : hours.toFixed(1)} год`; }
function formatDateTime(value: string | null, timezone: string): string { if (!value) return "—"; const date = new Date(value); if (Number.isNaN(date.getTime())) return "—"; try { return new Intl.DateTimeFormat("uk-UA", { timeZone: timezone, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).format(date); } catch { return new Intl.DateTimeFormat("uk-UA", { timeZone: "Europe/Kyiv", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).format(date); } }
