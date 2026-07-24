import { useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  CircleOff,
  Clock3,
  FileClock,
  Gauge,
  LoaderCircle,
  MessageSquarePlus,
  RadioTower,
  ShieldCheck,
} from "lucide-react";

import type {
  AttributedTelemetrySample,
  AuditLogEntry,
  LaboratorySession,
  SessionNote,
  SessionStage,
  SessionStageType,
} from "@/lib/sessions/types";
import {
  formatDuration,
  selectEnergyUnits,
  selectTemperatureSamples,
  sessionElapsedMs,
  SESSION_STATE_LABELS,
  type WorkspaceConnectionState,
} from "@/lib/sessions/view-model";

import type { SessionWorkspaceData } from "./use-session-workspace";

const CONNECTION_LABELS: Record<WorkspaceConnectionState, string> = {
  connecting: "Підключення",
  live: "Live",
  stale: "Застарілі дані",
  offline: "Offline · cached snapshot",
  error: "Помилка",
};

export function SessionHero({
  session,
  connectionState,
  clock,
  readOnly,
}: {
  session: LaboratorySession;
  connectionState: WorkspaceConnectionState;
  clock: number;
  readOnly: boolean;
}) {
  const connectionTone =
    connectionState === "live"
      ? "border-emerald-300/20 bg-emerald-400/[0.06] text-emerald-300"
      : connectionState === "stale" || connectionState === "offline"
        ? "border-amber-300/20 bg-amber-400/[0.06] text-amber-300"
        : "border-red-300/20 bg-red-400/[0.06] text-red-300";

  return (
    <section className="panel p-5 sm:p-6">
      <div className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[10px] text-cyan-300">{session.session_number}</span>
            <span className="rounded-full border border-blue-300/15 bg-blue-400/[0.05] px-2.5 py-1 text-[8px] font-semibold text-cyan-200">
              {SESSION_STATE_LABELS[session.state]}
            </span>
            <span className={`rounded-full border px-2.5 py-1 text-[8px] font-semibold ${connectionTone}`}>
              ● {CONNECTION_LABELS[connectionState]}
            </span>
            {readOnly && (
              <span className="rounded-full border border-slate-300/15 bg-slate-400/[0.05] px-2.5 py-1 text-[8px] font-semibold text-slate-300">
                Read-only
              </span>
            )}
          </div>
          <h1 className="mt-3 truncate text-2xl font-semibold text-white sm:text-3xl">{session.title}</h1>
          <p className="mt-2 text-[11px] leading-5 text-slate-400">
            {session.test_object} · {session.model ?? "модель не вказана"} · S/N {session.serial_number ?? "—"}
          </p>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:min-w-[620px]">
          <HeroMetric label="Elapsed" value={formatDuration(sessionElapsedMs(session, clock))} icon={Clock3} />
          <HeroMetric label="Node" value={session.node_id} icon={RadioTower} />
          <HeroMetric label="Limits" value={`v${session.active_limit_version ?? "—"}`} icon={Gauge} />
          <HeroMetric
            label="Snapshot"
            value={session.active_config_snapshot_id ? "Frozen" : "Pending"}
            icon={ShieldCheck}
          />
        </div>
      </div>
    </section>
  );
}

export function TemperatureAndChart({ data }: { data: SessionWorkspaceData }) {
  const temperatures = selectTemperatureSamples(data.latest);
  const history = data.history.filter((sample) => sample.metric === "temperature.probe");

  return (
    <section className="grid gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
        {temperatures.map(({ channelId, sample }) => (
          <div key={channelId} className="panel p-5">
            <div className="flex items-center justify-between">
              <div>
                <p className="font-mono text-[10px] text-cyan-300">{channelId}</p>
                <p className="mt-1 text-[9px] text-slate-600">K106 · temperature.probe</p>
              </div>
              <QualityIcon sample={sample} />
            </div>
            <p className="mt-5 text-4xl font-semibold tracking-tight text-white">
              {sample?.value?.toFixed(1) ?? "—"}
              <span className="ml-2 text-base font-medium text-slate-500">°C</span>
            </p>
            <p className="mt-3 text-[9px] text-slate-500">
              {sample ? `${sample.quality} · ${formatTime(sample.captured_at)}` : "Немає attributed telemetry"}
            </p>
          </div>
        ))}
      </div>
      <div className="panel p-5 sm:p-6">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[9px] font-semibold tracking-[0.16em] text-cyan-300 uppercase">Live history</p>
            <h2 className="mt-2 text-sm font-semibold text-white">Температурний тренд · останні 24 години</h2>
          </div>
          <span className="rounded-full border border-white/[0.06] px-2.5 py-1 text-[8px] text-slate-500">
            Alarm markers: {history.filter((item) => item.alarm).length}
          </span>
        </div>
        <TemperatureChart samples={history} />
      </div>
    </section>
  );
}

export function EnergyGrid({ samples }: { samples: AttributedTelemetrySample[] }) {
  const units = selectEnergyUnits(samples);
  return (
    <section className="panel">
      <div className="border-b border-white/[0.055] p-5">
        <p className="text-[9px] font-semibold tracking-[0.16em] text-cyan-300 uppercase">LE-01MP</p>
        <h2 className="mt-2 text-sm font-semibold text-white">Енергетичні параметри 200–203</h2>
      </div>
      <div className="grid gap-px bg-white/[0.045] md:grid-cols-2 xl:grid-cols-4">
        {units.map((unit) => (
          <article key={unit.equipmentId} className="bg-[#0a1f3d] p-5">
            <div className="flex items-center justify-between">
              <p className="font-mono text-[10px] text-cyan-300">{unit.equipmentId}</p>
              <span className="text-[8px] text-slate-500">quality: {unit.quality}</span>
            </div>
            <p className="mt-4 text-2xl font-semibold text-white">
              {number(unit.activePower)} <span className="text-[10px] text-slate-500">W</span>
            </p>
            <dl className="mt-4 grid grid-cols-2 gap-3 text-[9px]">
              <MetricTerm label="Voltage" value={`${number(unit.voltage)} V`} />
              <MetricTerm label="Current" value={`${number(unit.current)} A`} />
              <MetricTerm label="Frequency" value={`${number(unit.frequency)} Hz`} />
              <MetricTerm label="Power factor" value={number(unit.powerFactor)} />
            </dl>
          </article>
        ))}
      </div>
    </section>
  );
}

export function StageTimeline({
  stages,
  currentStageId,
  readOnly,
  mutating,
  onAdvance,
}: {
  stages: SessionStage[];
  currentStageId: string | null;
  readOnly: boolean;
  mutating: boolean;
  onAdvance: (input: { stageType: SessionStageType; name: string; plannedDurationMinutes: number }) => Promise<void>;
}) {
  const [stageType, setStageType] = useState<SessionStageType>("main_test");
  const [name, setName] = useState("Основне випробування");
  const [minutes, setMinutes] = useState(60);

  return (
    <section className="panel p-5 sm:p-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-[9px] font-semibold tracking-[0.16em] text-cyan-300 uppercase">Stage timeline</p>
          <h2 className="mt-2 text-sm font-semibold text-white">Зафіксовані межі етапів</h2>
        </div>
        {!readOnly && (
          <div className="grid gap-2 sm:grid-cols-[170px_220px_110px_auto]">
            <select className="form-input" value={stageType} onChange={(event) => setStageType(event.target.value as SessionStageType)}>
              {[
                "preparation",
                "preconditioning",
                "stabilization",
                "main_test",
                "defrost",
                "recovery",
                "completion",
                "report",
              ].map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
            <input className="form-input" value={name} onChange={(event) => setName(event.target.value)} />
            <input type="number" min={0} className="form-input" value={minutes} onChange={(event) => setMinutes(Number(event.target.value))} />
            <button
              className="primary-button"
              disabled={mutating || !name.trim()}
              onClick={() => void onAdvance({ stageType, name: name.trim(), plannedDurationMinutes: minutes })}
            >
              Додати етап
            </button>
          </div>
        )}
      </div>
      <div className="mt-5 grid gap-3 lg:grid-cols-4">
        {stages.length === 0 ? (
          <Empty label="Етапи ще не зафіксовані" />
        ) : (
          stages.map((stage) => (
            <article
              key={stage.id}
              className={`rounded-2xl border p-4 ${
                stage.id === currentStageId
                  ? "border-blue-400/35 bg-blue-500/[0.08]"
                  : "border-white/[0.06] bg-white/[0.02]"
              }`}
            >
              <p className="font-mono text-[9px] text-cyan-300">#{stage.sequence_index + 1}</p>
              <h3 className="mt-2 text-[11px] font-semibold text-white">{stage.name}</h3>
              <p className="mt-1 text-[9px] text-slate-500">{stage.stage_type}</p>
              <p className="mt-3 text-[8px] text-slate-600">
                {stage.entered_at ? formatTime(stage.entered_at) : "not entered"}
                {stage.exited_at ? ` → ${formatTime(stage.exited_at)}` : ""}
              </p>
            </article>
          ))
        )}
      </div>
    </section>
  );
}

export function NotesAndAudit({
  notes,
  audit,
  readOnly,
  mutating,
  onAddNote,
}: {
  notes: SessionNote[];
  audit: AuditLogEntry[];
  readOnly: boolean;
  mutating: boolean;
  onAddNote: (body: string) => Promise<void>;
}) {
  const [body, setBody] = useState("");
  return (
    <section className="grid gap-4 xl:grid-cols-2">
      <div className="panel p-5 sm:p-6">
        <div className="flex items-center gap-2">
          <MessageSquarePlus className="h-4 w-4 text-cyan-300" />
          <h2 className="text-sm font-semibold text-white">Примітки оператора</h2>
        </div>
        {!readOnly && (
          <div className="mt-4 flex gap-2">
            <textarea
              value={body}
              onChange={(event) => setBody(event.target.value)}
              className="min-h-20 flex-1 rounded-xl border border-white/[0.08] bg-white/[0.03] p-3 text-[11px] text-slate-100 outline-none focus:border-blue-400/40"
              placeholder="Що відбулося на поточному етапі?"
            />
            <button
              className="primary-button self-end"
              disabled={mutating || !body.trim()}
              onClick={() => {
                const value = body;
                setBody("");
                void onAddNote(value);
              }}
            >
              Додати
            </button>
          </div>
        )}
        <div className="mt-4 max-h-80 space-y-2 overflow-y-auto scrollbar-thin">
          {notes.length === 0 ? (
            <Empty label="Приміток немає" />
          ) : (
            notes.map((note) => (
              <article key={note.id} className="rounded-xl border border-white/[0.055] bg-white/[0.02] p-3">
                <p className="text-[10px] leading-5 text-slate-300">{note.body}</p>
                <p className="mt-2 text-[8px] text-slate-600">
                  {note.author_id} · {formatDateTime(note.created_at)}
                </p>
              </article>
            ))
          )}
        </div>
      </div>
      <div className="panel p-5 sm:p-6">
        <div className="flex items-center gap-2">
          <FileClock className="h-4 w-4 text-cyan-300" />
          <h2 className="text-sm font-semibold text-white">Immutable audit</h2>
        </div>
        <div className="mt-4 max-h-[390px] space-y-2 overflow-y-auto scrollbar-thin">
          {audit.length === 0 ? (
            <Empty label="Audit events не знайдені" />
          ) : (
            audit.map((entry) => (
              <article key={entry.id} className="rounded-xl border border-white/[0.055] bg-white/[0.02] p-3">
                <div className="flex items-start justify-between gap-3">
                  <p className="text-[10px] font-semibold text-slate-200">{entry.action}</p>
                  <span className="text-[8px] text-slate-600">{formatDateTime(entry.occurred_at)}</span>
                </div>
                <p className="mt-1 text-[9px] text-slate-500">
                  {entry.actor_id} · {entry.actor_source} · {entry.entity_type}
                </p>
              </article>
            ))
          )}
        </div>
      </div>
    </section>
  );
}

export function ConfigurationEvidence({ data }: { data: SessionWorkspaceData }) {
  return (
    <section className="panel p-5 sm:p-6">
      <div className="flex items-center gap-2">
        <ShieldCheck className="h-4 w-4 text-cyan-300" />
        <h2 className="text-sm font-semibold text-white">Configuration evidence</h2>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-4">
        <Info label="Bindings" value={`${data.configuration.bindings.length} / 34`} />
        <Info label="Limits" value={`v${data.session.active_limit_version ?? "—"} · ${data.configuration.active_limits.length} rules`} />
        <Info label="Snapshots" value={String(data.configuration.snapshots.length)} />
        <Info label="Content SHA-256" value={data.configuration.active_snapshot?.content_sha256.slice(0, 16) ?? "pending"} mono />
      </div>
    </section>
  );
}

export function WorkspaceLoading() {
  return (
    <div className="panel grid min-h-[580px] place-items-center">
      <div className="text-center">
        <LoaderCircle className="mx-auto h-7 w-7 animate-spin text-cyan-300" />
        <p className="mt-3 text-[11px] text-slate-500">Завантаження real session snapshot…</p>
      </div>
    </div>
  );
}

export function WorkspaceError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="panel grid min-h-[500px] place-items-center p-6 text-center">
      <div>
        <CircleOff className="mx-auto h-8 w-8 text-amber-300" />
        <h2 className="mt-3 text-lg font-semibold text-white">Session workspace недоступний</h2>
        <p className="mt-2 max-w-xl text-[11px] leading-5 text-slate-400">{message}</p>
        <button className="primary-button mt-4" onClick={onRetry}>Повторити</button>
      </div>
    </div>
  );
}

function TemperatureChart({ samples }: { samples: AttributedTelemetrySample[] }) {
  const series = useMemo(() => {
    const recent = [...samples]
      .filter((sample) => sample.value !== null)
      .sort((a, b) => a.captured_at.localeCompare(b.captured_at))
      .slice(-120);
    const values = recent.map((sample) => sample.value as number);
    const min = values.length ? Math.min(...values) : 0;
    const max = values.length ? Math.max(...values) : 1;
    const range = Math.max(1, max - min);
    const byChannel = new Map<string, AttributedTelemetrySample[]>();
    for (const sample of recent) {
      byChannel.set(sample.channel_id, [...(byChannel.get(sample.channel_id) ?? []), sample]);
    }
    return [...byChannel.entries()].map(([channel, channelSamples]) => ({
      channel,
      points: channelSamples
        .map((sample, index) => {
          const x = channelSamples.length === 1 ? 50 : (index / (channelSamples.length - 1)) * 100;
          const y = 92 - ((((sample.value as number) - min) / range) * 78);
          return `${x.toFixed(2)},${y.toFixed(2)}`;
        })
        .join(" "),
      alarms: channelSamples.filter((sample) => sample.alarm),
    }));
  }, [samples]);

  if (series.length === 0) {
    return <div className="mt-5 grid h-72 place-items-center text-[10px] text-slate-600">History ще порожня</div>;
  }

  return (
    <div className="mt-5">
      <svg viewBox="0 0 100 100" className="h-72 w-full overflow-visible" role="img" aria-label="Температурний графік">
        {[20, 40, 60, 80].map((y) => (
          <line key={y} x1="0" y1={y} x2="100" y2={y} stroke="rgba(148,163,184,.12)" strokeWidth=".25" />
        ))}
        {series.map((item, index) => (
          <polyline
            key={item.channel}
            points={item.points}
            fill="none"
            stroke={index === 0 ? "#00c6e0" : "#7ed321"}
            strokeWidth="1.25"
            vectorEffect="non-scaling-stroke"
          />
        ))}
        {samples
          .filter((sample) => sample.alarm)
          .slice(-12)
          .map((sample, index) => (
            <circle key={`${sample.event_id}-${index}`} cx={90 - index * 5} cy={12} r="1.2" fill="#ff4d4f" />
          ))}
      </svg>
      <div className="flex flex-wrap gap-3 text-[9px] text-slate-500">
        <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-cyan-400" />106-03</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-lime-400" />106-04</span>
        <span><AlertTriangle className="mr-1 inline h-3 w-3 text-red-400" />alarm marker</span>
      </div>
    </div>
  );
}

function QualityIcon({ sample }: { sample: AttributedTelemetrySample | null }) {
  if (!sample) return <CircleOff className="h-5 w-5 text-slate-600" aria-label="Немає даних" />;
  if (sample.alarm) return <AlertTriangle className="h-5 w-5 text-red-400" aria-label="Тривога" />;
  if (sample.quality !== "valid") return <Activity className="h-5 w-5 text-amber-300" aria-label={`Якість ${sample.quality}`} />;
  return <CheckCircle2 className="h-5 w-5 text-emerald-300" aria-label="Валідні дані" />;
}

function HeroMetric({ label, value, icon: Icon }: { label: string; value: string; icon: typeof Clock3 }) {
  return (
    <div className="rounded-2xl border border-white/[0.06] bg-white/[0.025] p-3">
      <Icon className="h-4 w-4 text-cyan-300" />
      <p className="mt-3 truncate text-[12px] font-semibold text-white">{value}</p>
      <p className="mt-1 text-[8px] tracking-[0.12em] text-slate-600 uppercase">{label}</p>
    </div>
  );
}

function MetricTerm({ label, value }: { label: string; value: string }) {
  return <div><dt className="text-slate-600">{label}</dt><dd className="mt-1 font-medium text-slate-300">{value}</dd></div>;
}

function Info({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-2xl border border-white/[0.06] bg-white/[0.025] p-4">
      <p className="text-[8px] tracking-[0.12em] text-slate-600 uppercase">{label}</p>
      <p className={`mt-2 truncate text-[11px] font-semibold text-white ${mono ? "font-mono" : ""}`}>{value}</p>
    </div>
  );
}

function Empty({ label }: { label: string }) {
  return <div className="rounded-xl border border-dashed border-white/[0.08] p-4 text-[10px] text-slate-600">{label}</div>;
}

function number(value: number | null): string {
  return value === null ? "—" : new Intl.NumberFormat("uk-UA", { maximumFractionDigits: 2 }).format(value);
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat("uk-UA", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(value));
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("uk-UA", { dateStyle: "short", timeStyle: "medium" }).format(new Date(value));
}
