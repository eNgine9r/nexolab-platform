"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  LoaderCircle,
  RefreshCw,
  Search,
  ShieldAlert,
  Siren,
  WifiOff,
} from "lucide-react";

import { invalidateOverviewAlertsReadModel } from "@/features/overview/use-overview-alerts-read-model";
import {
  createAlertApiClient,
  createAlertIdempotencyKey,
  type AlertListQuery,
} from "@/lib/alerts/api-client";
import type { AlertInstance, AlertSeverity, AlertState, AlertTransition } from "@/lib/alerts/types";

const STATE_FILTERS: Array<{ value: "all" | AlertState; label: string }> = [
  { value: "all", label: "Усі" },
  { value: "active", label: "Активні" },
  { value: "acknowledged", label: "Підтверджені" },
  { value: "resolved", label: "Вирішені" },
  { value: "closed", label: "Закриті" },
];

const SEVERITY_FILTERS: Array<{ value: "all" | AlertSeverity; label: string }> = [
  { value: "all", label: "Усі рівні" },
  { value: "critical", label: "Критичні" },
  { value: "alarm", label: "Аварії" },
  { value: "warning", label: "Попередження" },
  { value: "system", label: "Системні" },
  { value: "information", label: "Інформація" },
];

const STATE_LABELS: Record<AlertState, string> = {
  active: "Активна",
  acknowledged: "Підтверджена",
  resolved: "Вирішена",
  closed: "Закрита",
};

const SEVERITY_LABELS: Record<AlertSeverity, string> = {
  information: "Інформація",
  warning: "Попередження",
  alarm: "Аварія",
  critical: "Критична",
  system: "Системна",
};

function severityClass(severity: AlertSeverity): string {
  if (severity === "critical") return "border-red-300/25 bg-red-400/[0.08] text-red-200";
  if (severity === "alarm") return "border-orange-300/25 bg-orange-400/[0.08] text-orange-200";
  if (severity === "warning") return "border-amber-300/25 bg-amber-400/[0.08] text-amber-200";
  if (severity === "system") return "border-violet-300/25 bg-violet-400/[0.08] text-violet-200";
  return "border-cyan-300/20 bg-cyan-400/[0.07] text-cyan-200";
}

function stateClass(state: AlertState): string {
  if (state === "active") return "border-red-300/20 bg-red-400/[0.06] text-red-200";
  if (state === "acknowledged") return "border-blue-300/20 bg-blue-400/[0.06] text-blue-200";
  if (state === "resolved") return "border-emerald-300/20 bg-emerald-400/[0.06] text-emerald-200";
  return "border-slate-300/15 bg-slate-400/[0.05] text-slate-300";
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("uk-UA", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));
}

function formatNumber(value: number | null, unit?: unknown): string {
  if (value === null) return "—";
  const suffix = typeof unit === "string" && unit.trim() ? ` ${unit}` : "";
  return `${new Intl.NumberFormat("uk-UA", { maximumFractionDigits: 3 }).format(value)}${suffix}`;
}

function durationLabel(alert: AlertInstance, now: number): string {
  const start = new Date(alert.triggered_at).getTime();
  const end = alert.closed_at
    ? new Date(alert.closed_at).getTime()
    : alert.resolved_at
      ? new Date(alert.resolved_at).getTime()
      : now;
  const seconds = Math.max(0, Math.floor((end - start) / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  if (hours > 0) return `${hours} год ${minutes} хв`;
  if (minutes > 0) return `${minutes} хв ${remainder} с`;
  return `${remainder} с`;
}

export function AlertsWorkspace({
  telemetryPoints,
  telemetrySelector,
}: {
  telemetryPoints?: readonly string[];
  telemetrySelector?: ReactNode;
}) {
  const [alerts, setAlerts] = useState<AlertInstance[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [transitions, setTransitions] = useState<AlertTransition[]>([]);
  const [stateFilter, setStateFilter] = useState<"all" | AlertState>("all");
  const [severityFilter, setSeverityFilter] = useState<"all" | AlertSeverity>("all");
  const [query, setQuery] = useState("");
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [mutating, setMutating] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [actionError, setActionError] = useState<Error | null>(null);
  const [lastSuccessfulAt, setLastSuccessfulAt] = useState<number | null>(null);
  const [generation, setGeneration] = useState(0);
  const [now, setNow] = useState(() => Date.now());

  const selected = useMemo(() => alerts.find((item) => item.id === selectedId) ?? null, [alerts, selectedId]);

  const load = useCallback(
    async (signal: AbortSignal, quiet = false) => {
      if (!quiet) setLoading(true);
      try {
        const client = createAlertApiClient();
        const query: AlertListQuery = {
          state: stateFilter === "all" ? undefined : stateFilter,
          severity: severityFilter === "all" ? undefined : severityFilter,
          telemetryPoints,
          limit: 200,
        };
        const page = await client.listAlerts(query, signal);
        setAlerts(page.items);
        setTotalCount(page.count);
        setSelectedId((current) => {
          if (current && page.items.some((item) => item.id === current)) return current;
          return page.items[0]?.id ?? null;
        });
        setError(null);
        setLastSuccessfulAt(Date.now());
      } catch (nextError) {
        if (!signal.aborted) {
          setError(nextError instanceof Error ? nextError : new Error("Не вдалося завантажити тривоги."));
        }
      } finally {
        if (!signal.aborted && !quiet) setLoading(false);
      }
    },
    [severityFilter, stateFilter, telemetryPoints],
  );

  useEffect(() => {
    const controller = new AbortController();
    const initial = window.setTimeout(() => void load(controller.signal), 0);
    const refresh = window.setInterval(() => void load(controller.signal, true), 5_000);
    return () => {
      controller.abort();
      window.clearTimeout(initial);
      window.clearInterval(refresh);
    };
  }, [generation, load]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    const controller = new AbortController();
    const initial = window.setTimeout(() => {
      setDetailLoading(true);
      void createAlertApiClient()
        .listTransitions(selectedId, controller.signal)
        .then((page) => {
          if (!controller.signal.aborted) setTransitions(page.items);
        })
        .catch((nextError) => {
          if (!controller.signal.aborted) {
            setActionError(
              nextError instanceof Error ? nextError : new Error("Не вдалося завантажити історію тривоги."),
            );
          }
        })
        .finally(() => {
          if (!controller.signal.aborted) setDetailLoading(false);
        });
    }, 0);
    return () => {
      controller.abort();
      window.clearTimeout(initial);
    };
  }, [selectedId, selected?.lock_version]);

  const visibleAlerts = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("uk-UA");
    if (!normalized) return alerts;
    return alerts.filter((alert) =>
      [alert.node_id, alert.equipment_id, alert.channel_id, alert.metric, alert.session_id]
        .filter(Boolean)
        .some((value) => value?.toLocaleLowerCase("uk-UA").includes(normalized)),
    );
  }, [alerts, query]);

  const stale = lastSuccessfulAt !== null && now - lastSuccessfulAt > 15_000;

  const refresh = () => {
    setLoading(true);
    setGeneration((value) => value + 1);
  };

  const runAction = async (action: "acknowledge" | "close") => {
    if (!selected) return;
    setMutating(true);
    setActionError(null);
    try {
      const client = createAlertApiClient();
      const response =
        action === "acknowledge"
          ? await client.acknowledge(selected.id, reason, createAlertIdempotencyKey(`ack:${selected.id}`))
          : await client.close(selected.id, reason, createAlertIdempotencyKey(`close:${selected.id}`));
      setAlerts((items) => items.map((item) => (item.id === response.alert.id ? response.alert : item)));
      setTransitions((items) => [
        response.transition,
        ...items.filter((item) => item.id !== response.transition.id),
      ]);
      setReason("");
      setLastSuccessfulAt(Date.now());
      invalidateOverviewAlertsReadModel();
    } catch (nextError) {
      setActionError(nextError instanceof Error ? nextError : new Error("Операцію не виконано."));
    } finally {
      setMutating(false);
    }
  };

  return (
    <div className="space-y-4" data-testid="alerts-workspace">
      <section className="panel p-5 sm:p-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <p className="text-[9px] font-semibold tracking-[0.18em] text-cyan-300 uppercase">
              Sprint 13 · Production Alerts
            </p>
            <h1 className="mt-2 text-2xl font-semibold text-white sm:text-3xl">Тривоги та події</h1>
            <p className="mt-2 max-w-3xl text-[12px] leading-6 text-slate-400">
              Організаційно ізольовані правила, evidence, verified actor attribution і контрольований
              lifecycle.
            </p>
          </div>
          <div className="grid grid-cols-4 gap-2 sm:min-w-[520px]">
            <Summary label="Усього у scope" value={totalCount} />
            <Summary
              label="Активні на сторінці"
              value={alerts.filter((item) => item.state === "active").length}
            />
            <Summary
              label="Підтверджені на сторінці"
              value={alerts.filter((item) => item.state === "acknowledged").length}
            />
            <Summary
              label="Критичні на сторінці"
              value={alerts.filter((item) => item.severity === "critical" && item.state !== "closed").length}
            />
          </div>
        </div>
      </section>

      {telemetrySelector}

      <section className="panel overflow-hidden">
        <div className="flex flex-col gap-3 border-b border-white/[0.055] p-4 xl:flex-row xl:items-center xl:justify-between xl:p-5">
          <div className="flex flex-wrap gap-2" aria-label="Фільтри lifecycle">
            {STATE_FILTERS.map((item) => (
              <button
                key={item.value}
                aria-pressed={stateFilter === item.value}
                onClick={() => setStateFilter(item.value)}
                className={`rounded-xl border px-3 py-2 text-[10px] font-semibold transition ${
                  stateFilter === item.value
                    ? "border-blue-400/40 bg-blue-500/10 text-cyan-200"
                    : "border-white/[0.065] bg-white/[0.02] text-slate-500 hover:text-slate-200"
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>
          <div className="flex flex-col gap-2 sm:flex-row">
            <select
              aria-label="Фільтр рівня"
              value={severityFilter}
              onChange={(event) => setSeverityFilter(event.target.value as "all" | AlertSeverity)}
              className="form-input sm:w-44"
            >
              {SEVERITY_FILTERS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
            <label className="relative min-w-0 flex-1 sm:w-72">
              <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-slate-600" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Вузол, обладнання, канал…"
                className="form-input pl-10"
              />
            </label>
            <button className="icon-button inline-grid" onClick={refresh} aria-label="Оновити тривоги">
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>

        {stale ? (
          <div
            className="flex items-center gap-2 border-b border-amber-300/15 bg-amber-400/[0.045] px-5 py-3 text-[10px] text-amber-200"
            data-testid="alerts-stale-state"
          >
            <WifiOff className="h-4 w-4" />
            Дані не оновлювалися понад 15 секунд. Показано останній підтверджений snapshot.
          </div>
        ) : null}

        {error ? (
          <div
            className="m-5 rounded-2xl border border-amber-300/15 bg-amber-400/[0.045] p-5"
            data-testid="alerts-error"
          >
            <div className="flex items-start gap-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 text-amber-300" />
              <div>
                <h2 className="text-sm font-semibold text-white">Alerts API недоступний</h2>
                <p className="mt-1 text-[11px] leading-5 text-slate-400">{error.message}</p>
                <button className="secondary-button mt-3" onClick={refresh}>
                  Повторити
                </button>
              </div>
            </div>
          </div>
        ) : loading ? (
          <div className="grid min-h-80 place-items-center text-slate-500">
            <div className="text-center">
              <LoaderCircle className="mx-auto h-6 w-6 animate-spin text-cyan-300" />
              <p className="mt-3 text-[11px]">Завантаження production alerts…</p>
            </div>
          </div>
        ) : visibleAlerts.length === 0 ? (
          <div className="grid min-h-80 place-items-center px-6 text-center" data-testid="alerts-empty-state">
            <div>
              <CheckCircle2 className="mx-auto h-9 w-9 text-emerald-400" />
              <h2 className="mt-3 text-sm font-semibold text-white">Тривог не знайдено</h2>
              <p className="mt-1 text-[11px] text-slate-500">
                Поточні фільтри не містять production alert instances.
              </p>
            </div>
          </div>
        ) : (
          <div className="grid min-h-[560px] xl:grid-cols-[minmax(360px,.9fr)_minmax(0,1.45fr)]">
            <div className="max-h-[760px] overflow-y-auto border-b border-white/[0.055] xl:border-r xl:border-b-0">
              {visibleAlerts.map((alert) => (
                <button
                  key={alert.id}
                  type="button"
                  data-testid={`alert-row-${alert.id}`}
                  onClick={() => {
                    setSelectedId(alert.id);
                    setActionError(null);
                    setReason("");
                  }}
                  className={`w-full border-b border-white/[0.045] p-4 text-left transition sm:p-5 ${
                    selectedId === alert.id ? "bg-blue-500/[0.07]" : "hover:bg-white/[0.025]"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className={`rounded-full border px-2 py-1 text-[8px] font-semibold ${severityClass(alert.severity)}`}
                        >
                          {SEVERITY_LABELS[alert.severity]}
                        </span>
                        <span
                          className={`rounded-full border px-2 py-1 text-[8px] font-semibold ${stateClass(alert.state)}`}
                        >
                          {STATE_LABELS[alert.state]}
                        </span>
                      </div>
                      <h2 className="mt-3 truncate text-sm font-semibold text-white">
                        {alert.equipment_id} · {alert.channel_id}
                      </h2>
                      <p className="mt-1 truncate font-mono text-[9px] text-cyan-300">{alert.metric}</p>
                    </div>
                    <Siren className="h-5 w-5 shrink-0 text-red-300" />
                  </div>
                  <div className="mt-4 grid grid-cols-3 gap-2 text-[9px]">
                    <MiniMetric
                      label="Тригер"
                      value={formatNumber(alert.trigger_value, alert.context.unit)}
                    />
                    <MiniMetric
                      label="Межа"
                      value={formatNumber(alert.trigger_threshold, alert.context.unit)}
                    />
                    <MiniMetric
                      label="Відхилення"
                      value={formatNumber(alert.maximum_deviation, alert.context.unit)}
                    />
                  </div>
                  <p className="mt-3 flex items-center gap-1.5 text-[9px] text-slate-600">
                    <Clock3 className="h-3 w-3" />
                    {formatDate(alert.triggered_at)} · {durationLabel(alert, now)}
                  </p>
                </button>
              ))}
            </div>

            {selected ? (
              <div className="p-4 sm:p-6" data-testid="alert-detail">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <div className="flex flex-wrap gap-2">
                      <span
                        className={`rounded-full border px-2.5 py-1 text-[9px] font-semibold ${severityClass(selected.severity)}`}
                      >
                        {SEVERITY_LABELS[selected.severity]}
                      </span>
                      <span
                        className={`rounded-full border px-2.5 py-1 text-[9px] font-semibold ${stateClass(selected.state)}`}
                      >
                        {STATE_LABELS[selected.state]}
                      </span>
                    </div>
                    <h2 className="mt-3 text-xl font-semibold text-white">
                      {selected.equipment_id} / {selected.channel_id}
                    </h2>
                    <p className="mt-1 font-mono text-[10px] text-cyan-300">{selected.metric}</p>
                  </div>
                  <div className="rounded-2xl border border-white/[0.06] bg-white/[0.025] px-4 py-3 text-right">
                    <p className="text-[8px] tracking-[0.12em] text-slate-600 uppercase">Тривалість</p>
                    <p className="mt-1 text-sm font-semibold text-white" data-testid="alert-duration">
                      {durationLabel(selected, now)}
                    </p>
                  </div>
                </div>

                <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  <DetailMetric
                    label="Trigger value"
                    value={formatNumber(selected.trigger_value, selected.context.unit)}
                  />
                  <DetailMetric
                    label="Trigger threshold"
                    value={formatNumber(selected.trigger_threshold, selected.context.unit)}
                  />
                  <DetailMetric
                    label="Clear threshold"
                    value={formatNumber(selected.clear_threshold, selected.context.unit)}
                  />
                  <DetailMetric
                    label="Maximum deviation"
                    value={formatNumber(selected.maximum_deviation, selected.context.unit)}
                  />
                </div>

                <div className="mt-6 grid gap-3 sm:grid-cols-2">
                  <ContextRow label="Організація" value={selected.organization_id} />
                  <ContextRow label="Вузол" value={selected.node_id} />
                  <ContextRow label="Сесія" value={selected.session_id ?? "Без сесії"} />
                  <ContextRow label="Етап" value={selected.stage_id ?? "Без етапу"} />
                  <ContextRow label="Binding" value={selected.binding_id ?? "Без binding"} />
                  <ContextRow label="Rule version" value={selected.rule_version_id} />
                </div>

                {(selected.state === "active" || selected.state === "resolved") && (
                  <div className="mt-6 rounded-2xl border border-blue-300/10 bg-blue-400/[0.035] p-4">
                    <label className="text-[9px] font-semibold tracking-[0.12em] text-slate-500 uppercase">
                      Причина оператора
                      <textarea
                        value={reason}
                        onChange={(event) => setReason(event.target.value)}
                        placeholder={
                          selected.state === "active"
                            ? "Що перевірено оператором…"
                            : "Чому alert можна контрольовано закрити…"
                        }
                        className="form-input mt-2 min-h-20 resize-y"
                      />
                    </label>
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      {selected.state === "active" ? (
                        <button
                          className="primary-button"
                          disabled={mutating || !reason.trim()}
                          onClick={() => void runAction("acknowledge")}
                          data-testid="acknowledge-alert"
                        >
                          {mutating ? (
                            <LoaderCircle className="h-4 w-4 animate-spin" />
                          ) : (
                            <ShieldAlert className="h-4 w-4" />
                          )}
                          Підтвердити тривогу
                        </button>
                      ) : (
                        <button
                          className="primary-button"
                          disabled={mutating || !reason.trim()}
                          onClick={() => void runAction("close")}
                          data-testid="close-alert"
                        >
                          {mutating ? (
                            <LoaderCircle className="h-4 w-4 animate-spin" />
                          ) : (
                            <CheckCircle2 className="h-4 w-4" />
                          )}
                          Закрити тривогу
                        </button>
                      )}
                      <span className="text-[9px] text-slate-600">
                        Actor визначає backend із verified JWT.
                      </span>
                    </div>
                  </div>
                )}

                {actionError ? (
                  <div
                    className="mt-4 flex items-start gap-2 rounded-2xl border border-red-300/15 bg-red-400/[0.045] p-4 text-[10px] text-red-200"
                    data-testid="alert-action-error"
                  >
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                    {actionError.message}
                  </div>
                ) : null}

                <div className="mt-6">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-white">Lifecycle audit</h3>
                    {detailLoading ? <LoaderCircle className="h-4 w-4 animate-spin text-cyan-300" /> : null}
                  </div>
                  <div className="mt-3 space-y-2" data-testid="alert-transitions">
                    {transitions.map((transition) => (
                      <div
                        key={transition.id}
                        className="rounded-2xl border border-white/[0.055] bg-white/[0.02] p-3"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-[10px] font-semibold text-slate-200">{transition.event_type}</p>
                          <p className="text-[8px] text-slate-600">{formatDate(transition.occurred_at)}</p>
                        </div>
                        <p className="mt-1 text-[9px] text-slate-500">
                          {transition.previous_state ?? "—"} → {transition.next_state} · {transition.actor_id}{" "}
                          · {transition.actor_source}
                        </p>
                        {transition.reason ? (
                          <p className="mt-2 text-[10px] text-slate-300">{transition.reason}</p>
                        ) : null}
                      </div>
                    ))}
                    {!detailLoading && transitions.length === 0 ? (
                      <p className="rounded-2xl border border-dashed border-white/[0.07] p-4 text-center text-[10px] text-slate-600">
                        Lifecycle transitions відсутні.
                      </p>
                    ) : null}
                  </div>
                </div>
              </div>
            ) : (
              <div className="grid min-h-96 place-items-center p-8 text-center">
                <div>
                  <ShieldAlert className="mx-auto h-8 w-8 text-slate-600" />
                  <p className="mt-3 text-[11px] text-slate-500">
                    Оберіть alert для перегляду evidence та lifecycle.
                  </p>
                </div>
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

function Summary({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-2xl border border-white/[0.06] bg-white/[0.025] p-3 text-center">
      <p className="text-xl font-semibold text-white">{value}</p>
      <p className="mt-1 text-[8px] tracking-[0.12em] text-slate-600 uppercase">{label}</p>
    </div>
  );
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/[0.05] bg-slate-950/20 p-2">
      <p className="text-[7px] tracking-[0.1em] text-slate-700 uppercase">{label}</p>
      <p className="mt-1 truncate text-[9px] font-semibold text-slate-300">{value}</p>
    </div>
  );
}

function DetailMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/[0.06] bg-white/[0.025] p-4">
      <p className="text-[8px] tracking-[0.12em] text-slate-600 uppercase">{label}</p>
      <p className="mt-2 text-base font-semibold text-white">{value}</p>
    </div>
  );
}

function ContextRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-w-0 items-center justify-between gap-4 rounded-xl border border-white/[0.045] bg-slate-950/15 px-3 py-2.5">
      <span className="text-[8px] tracking-[0.1em] text-slate-600 uppercase">{label}</span>
      <span className="truncate font-mono text-[9px] text-slate-300" title={value}>
        {value}
      </span>
    </div>
  );
}
