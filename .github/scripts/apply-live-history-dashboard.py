from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


write(
    "src/lib/telemetry/history-series.ts",
    '''import type { TelemetrySample } from "./types";

export const PRODUCTION_HISTORY_CHANNELS = ["106-03", "106-04"] as const;

export type TemperatureHistoryPoint = {
  eventId: string;
  capturedAt: string;
  value: number;
  x: number;
  y: number;
};

export type TemperatureHistorySeries = {
  channelId: string;
  points: TemperatureHistoryPoint[];
  path: string;
};

export type TemperatureHistoryChart = {
  series: TemperatureHistorySeries[];
  minimum: number | null;
  maximum: number | null;
  from: string;
  to: string;
};

function isTemperature(sample: TelemetrySample): boolean {
  const metric = sample.metric.trim().toLowerCase().replaceAll("-", "_").replaceAll(".", "_");
  return metric === "temperature" || metric.startsWith("temperature_");
}

function usable(sample: TelemetrySample): sample is TelemetrySample & { value: number } {
  return (
    sample.quality === "valid" &&
    sample.value !== null &&
    Number.isFinite(sample.value) &&
    isTemperature(sample) &&
    PRODUCTION_HISTORY_CHANNELS.includes(
      sample.channel_id as (typeof PRODUCTION_HISTORY_CHANNELS)[number],
    )
  );
}

export function mergeTelemetryHistory(
  history: readonly TelemetrySample[],
  latest: readonly TelemetrySample[],
): TelemetrySample[] {
  const byEventId = new Map<string, TelemetrySample>();
  for (const sample of [...history, ...latest]) {
    byEventId.set(sample.event_id, sample);
  }
  return [...byEventId.values()].sort(
    (left, right) => Date.parse(left.captured_at) - Date.parse(right.captured_at),
  );
}

export function buildTemperatureHistoryChart(
  samples: readonly TelemetrySample[],
  window: { from: string; to: string },
): TemperatureHistoryChart {
  const fromMs = Date.parse(window.from);
  const toMs = Date.parse(window.to);
  const safeFrom = Number.isFinite(fromMs) ? fromMs : Date.now() - 60 * 60 * 1000;
  const safeTo = Number.isFinite(toMs) && toMs > safeFrom ? toMs : safeFrom + 60 * 60 * 1000;
  const accepted = samples.filter(usable).filter((sample) => {
    const captured = Date.parse(sample.captured_at);
    return Number.isFinite(captured) && captured >= safeFrom && captured <= safeTo;
  });
  const values = accepted.map((sample) => sample.value);
  const minimum = values.length > 0 ? Math.min(...values) : null;
  const maximum = values.length > 0 ? Math.max(...values) : null;
  const spread = minimum === null || maximum === null ? 1 : Math.max(1, maximum - minimum);
  const lower = minimum === null ? 0 : minimum - spread * 0.12;
  const upper = maximum === null ? 1 : maximum + spread * 0.12;
  const valueSpan = Math.max(1, upper - lower);
  const timeSpan = Math.max(1, safeTo - safeFrom);

  const series = PRODUCTION_HISTORY_CHANNELS.map((channelId) => {
    const channelSamples = accepted.filter((sample) => sample.channel_id === channelId);
    const points = channelSamples.map((sample) => {
      const captured = Date.parse(sample.captured_at);
      return {
        eventId: sample.event_id,
        capturedAt: sample.captured_at,
        value: sample.value,
        x: 32 + ((captured - safeFrom) / timeSpan) * 568,
        y: 20 + (1 - (sample.value - lower) / valueSpan) * 135,
      };
    });
    return {
      channelId,
      points,
      path: points
        .map((point, index) => `${index === 0 ? "M" : "L"}${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
        .join(" "),
    };
  }).filter((item) => item.points.length > 0);

  return {
    series,
    minimum,
    maximum,
    from: new Date(safeFrom).toISOString(),
    to: new Date(safeTo).toISOString(),
  };
}
''',
)

write(
    "src/lib/telemetry/history-series.test.ts",
    '''import { describe, expect, it } from "vitest";

import type { TelemetrySample } from "./types";
import { buildTemperatureHistoryChart, mergeTelemetryHistory } from "./history-series";

function sample(
  eventId: string,
  channelId: string,
  capturedAt: string,
  value: number | null,
  quality: TelemetrySample["quality"] = "valid",
): TelemetrySample {
  return {
    event_id: eventId,
    node_id: "edge-01",
    captured_at: capturedAt,
    metric: "temperature.probe",
    value,
    unit: "degC",
    quality,
    source: "dixell-xjp60d",
    equipment_id: "K106",
    channel_id: channelId,
    alarm: null,
    raw_value: value === null ? null : Math.round(value * 10),
    raw_status: null,
  };
}

describe("temperature history series", () => {
  it("deduplicates history and latest samples in chronological order", () => {
    const first = sample("event-1", "106-03", "2026-07-26T05:00:00Z", 3.2);
    const second = sample("event-2", "106-03", "2026-07-26T05:10:00Z", 3.4);

    expect(mergeTelemetryHistory([second, first], [second]).map((item) => item.event_id)).toEqual([
      "event-1",
      "event-2",
    ]);
  });

  it("builds bounded paths only from valid production temperature channels", () => {
    const chart = buildTemperatureHistoryChart(
      [
        sample("event-1", "106-03", "2026-07-26T05:00:00Z", 3.2),
        sample("event-2", "106-03", "2026-07-26T05:30:00Z", 4.1),
        sample("event-3", "106-04", "2026-07-26T05:45:00Z", 2.8),
        sample("event-4", "106-04", "2026-07-26T05:50:00Z", null, "sensor_error"),
        sample("event-5", "115-04", "2026-07-26T05:55:00Z", 8.0),
      ],
      { from: "2026-07-26T05:00:00Z", to: "2026-07-26T06:00:00Z" },
    );

    expect(chart.series.map((item) => item.channelId)).toEqual(["106-03", "106-04"]);
    expect(chart.series[0].path).toMatch(/^M/);
    expect(chart.series.flatMap((item) => item.points)).toHaveLength(3);
    expect(chart.minimum).toBe(2.8);
    expect(chart.maximum).toBe(4.1);
    expect(chart.series.flatMap((item) => item.points).every((point) => point.x >= 32 && point.x <= 600)).toBe(
      true,
    );
  });
});
''',
)

write(
    "src/hooks/use-dashboard-telemetry.ts",
    '''"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { kpis as demoKpis } from "@/data/dashboard";
import { createAuthenticatedFetch } from "@/features/security/security-session";
import { createSupabaseCredentialProvider } from "@/features/security/supabase-auth";
import { createTelemetryAdapter } from "@/lib/telemetry/create-adapter";
import {
  buildLiveDashboardKpis,
  createDashboardTelemetryStore,
  deriveDashboardTelemetry,
  mergeDashboardTelemetry,
  selectProductionTemperatures,
  type DashboardKpiValue,
  type DashboardTelemetryStatus,
  type DashboardTelemetryStore,
  type DashboardTelemetryView,
} from "@/lib/telemetry/dashboard-state";
import { getTelemetryRuntimeConfig } from "@/lib/telemetry/runtime-config";
import type {
  TelemetryAdapter,
  TelemetryConnectionState,
  TelemetryRuntimeConfig,
  TelemetrySample,
  TelemetrySubscription,
} from "@/lib/telemetry/types";

const CLOCK_TICK_MS = 5_000;
const STALE_AFTER_MS = 30_000;
const DEFAULT_SCOPE = "__default_organization__";
const HISTORY_HOURS = { "1h": 1, "6h": 6, "24h": 24 } as const;

interface RuntimeConfigResult {
  config: TelemetryRuntimeConfig | null;
  error: Error | null;
}

export type DashboardHistoryRange = keyof typeof HISTORY_HOURS;
export type DashboardHistoryStatus = "idle" | "loading" | "ready" | "error";

export interface DashboardTelemetryOptions {
  enabled?: boolean;
  organizationId?: string | null;
}

export interface DashboardTelemetryModel {
  mode: "demo" | "live";
  status: DashboardTelemetryStatus;
  view: DashboardTelemetryView | null;
  kpis: readonly DashboardKpiValue[] | typeof demoKpis;
  temperatures: TelemetrySample[];
  historySamples: TelemetrySample[];
  historyRange: DashboardHistoryRange;
  historyStatus: DashboardHistoryStatus;
  historyWindow: { from: string; to: string } | null;
  historyError: Error | null;
  setHistoryRange: (range: DashboardHistoryRange) => void;
  retryHistory: () => void;
  error: Error | null;
  retry: () => void;
}

function loadRuntimeConfig(): RuntimeConfigResult {
  try {
    return { config: getTelemetryRuntimeConfig(), error: null };
  } catch (error) {
    return {
      config: null,
      error: error instanceof Error ? error : new Error("Invalid telemetry configuration"),
    };
  }
}

function securedAdapter(
  config: TelemetryRuntimeConfig,
  organizationId: string | null,
): TelemetryAdapter {
  const credentialProvider = createSupabaseCredentialProvider(organizationId);
  return createTelemetryAdapter(config, {
    rest: {
      fetch: createAuthenticatedFetch(fetch.bind(globalThis), credentialProvider),
    },
    websocket: { credentials: credentialProvider },
  });
}

export function useDashboardTelemetry(options: DashboardTelemetryOptions = {}): DashboardTelemetryModel {
  const enabled = options.enabled ?? true;
  const selectedOrganizationId = options.organizationId?.trim() || null;
  const scopeKey = enabled ? (selectedOrganizationId ?? DEFAULT_SCOPE) : null;
  const [runtime] = useState<RuntimeConfigResult>(loadRuntimeConfig);
  const [store, setStore] = useState<DashboardTelemetryStore>(createDashboardTelemetryStore);
  const [activeScopeKey, setActiveScopeKey] = useState<string | null>(scopeKey);
  const [connectionState, setConnectionState] = useState<TelemetryConnectionState>(() =>
    runtime.config?.mode === "live" ? "connecting" : "disconnected",
  );
  const [hasLoadedSnapshot, setHasLoadedSnapshot] = useState(false);
  const [error, setError] = useState<Error | null>(runtime.error);
  const [clock, setClock] = useState(() => Date.now());
  const [generation, setGeneration] = useState(0);
  const [historyRange, setHistoryRange] = useState<DashboardHistoryRange>("24h");
  const [historySamples, setHistorySamples] = useState<TelemetrySample[]>([]);
  const [historyStatus, setHistoryStatus] = useState<DashboardHistoryStatus>(
    runtime.config?.mode === "live" ? "loading" : "idle",
  );
  const [historyWindow, setHistoryWindow] = useState<{ from: string; to: string } | null>(null);
  const [historyError, setHistoryError] = useState<Error | null>(null);
  const [activeHistoryKey, setActiveHistoryKey] = useState<string | null>(null);
  const [historyGeneration, setHistoryGeneration] = useState(0);
  const historyKey = scopeKey === null ? null : `${scopeKey}:${historyRange}`;

  const retry = useCallback(() => {
    if (runtime.config?.mode !== "live") return;
    setConnectionState("connecting");
    setHasLoadedSnapshot(false);
    setError(null);
    setStore(createDashboardTelemetryStore());
    setActiveScopeKey(scopeKey);
    setClock(Date.now());
    setGeneration((value) => value + 1);
  }, [runtime.config, scopeKey]);

  const retryHistory = useCallback(() => {
    if (runtime.config?.mode !== "live") return;
    setHistoryGeneration((value) => value + 1);
  }, [runtime.config]);

  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), CLOCK_TICK_MS);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const config = runtime.config;
    if (!config || config.mode === "demo" || !enabled || scopeKey === null) return;

    const controller = new AbortController();
    const organizationId =
      selectedOrganizationId ?? process.env.NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID?.trim() ?? null;
    const adapter = securedAdapter(config, organizationId);
    let subscription: TelemetrySubscription | null = null;
    let disposed = false;

    void Promise.resolve().then(() => {
      if (disposed) return;
      setActiveScopeKey(scopeKey);
      setConnectionState("connecting");
      setHasLoadedSnapshot(false);
      setError(null);
      setStore(createDashboardTelemetryStore());
      setClock(Date.now());
    });

    const commit = (samples: readonly TelemetrySample[]) => {
      if (disposed) return;
      setStore((current) => mergeDashboardTelemetry(current, samples, { now: Date.now() }));
      setError(null);
      setClock(Date.now());
    };

    const connectLive = () => {
      subscription = adapter.subscribe(
        { node_id: "edge-01" },
        {
          onSample: (sample) => commit([sample]),
          onStateChange: (state) => {
            if (disposed) return;
            setConnectionState(state);
            if (state === "connected") setError(null);
          },
          onError: (nextError) => {
            if (!disposed) setError(nextError);
          },
          onHeartbeat: () => setClock(Date.now()),
        },
      );
    };

    void adapter
      .latest({ node_id: "edge-01", limit: 1000 }, controller.signal)
      .then((snapshot) => {
        commit(snapshot.items);
        setHasLoadedSnapshot(true);
      })
      .catch((nextError: unknown) => {
        if (controller.signal.aborted || disposed) return;
        setHasLoadedSnapshot(true);
        setError(nextError instanceof Error ? nextError : new Error("Failed to load telemetry snapshot"));
      })
      .finally(() => {
        if (!disposed) connectLive();
      });

    return () => {
      disposed = true;
      controller.abort();
      subscription?.close();
    };
  }, [enabled, generation, runtime.config, scopeKey, selectedOrganizationId]);

  useEffect(() => {
    const config = runtime.config;
    if (!config || config.mode === "demo" || !enabled || historyKey === null) return;

    const controller = new AbortController();
    const organizationId =
      selectedOrganizationId ?? process.env.NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID?.trim() ?? null;
    const adapter = securedAdapter(config, organizationId);
    const to = new Date();
    const from = new Date(to.getTime() - HISTORY_HOURS[historyRange] * 60 * 60 * 1000);
    const nextWindow = { from: from.toISOString(), to: to.toISOString() };
    let disposed = false;

    void Promise.resolve().then(() => {
      if (disposed) return;
      setActiveHistoryKey(historyKey);
      setHistoryStatus("loading");
      setHistoryError(null);
      setHistorySamples([]);
      setHistoryWindow(nextWindow);
    });

    void adapter
      .history(
        {
          node_id: "edge-01",
          metric: "temperature.probe",
          from,
          to,
          limit: 1000,
        },
        controller.signal,
      )
      .then((response) => {
        if (disposed) return;
        setHistorySamples(response.items);
        setHistoryWindow(nextWindow);
        setHistoryStatus("ready");
        setHistoryError(null);
      })
      .catch((nextError: unknown) => {
        if (controller.signal.aborted || disposed) return;
        setHistorySamples([]);
        setHistoryWindow(nextWindow);
        setHistoryStatus("error");
        setHistoryError(nextError instanceof Error ? nextError : new Error("Failed to load telemetry history"));
      });

    return () => {
      disposed = true;
      controller.abort();
    };
  }, [enabled, historyGeneration, historyKey, historyRange, runtime.config, selectedOrganizationId]);

  const view = useMemo(() => {
    if (
      runtime.config?.mode !== "live" ||
      !enabled ||
      scopeKey === null ||
      activeScopeKey !== scopeKey
    ) {
      return null;
    }
    return deriveDashboardTelemetry(store, {
      now: clock,
      staleAfterMs: STALE_AFTER_MS,
      hasLoadedSnapshot,
      connectionState,
      error,
    });
  }, [
    activeScopeKey,
    clock,
    connectionState,
    enabled,
    error,
    hasLoadedSnapshot,
    runtime.config,
    scopeKey,
    store,
  ]);

  const visibleHistory = activeHistoryKey === historyKey ? historySamples : [];
  const visibleHistoryStatus = activeHistoryKey === historyKey ? historyStatus : "loading";
  const visibleHistoryWindow = activeHistoryKey === historyKey ? historyWindow : null;
  const visibleHistoryError = activeHistoryKey === historyKey ? historyError : null;

  if (!runtime.config) {
    return {
      mode: "live",
      status: "error",
      view: null,
      kpis: buildLiveDashboardKpis({
        status: "error",
        samples: [],
        freshSamples: [],
        lastCapturedAt: null,
        ageMs: null,
        rejectedFutureSamples: 0,
      }),
      temperatures: [],
      historySamples: [],
      historyRange,
      historyStatus: "error",
      historyWindow: null,
      historyError: runtime.error,
      setHistoryRange,
      retryHistory,
      error: runtime.error,
      retry,
    };
  }

  if (runtime.config.mode === "demo") {
    return {
      mode: "demo",
      status: "demo",
      view: null,
      kpis: demoKpis,
      temperatures: [],
      historySamples: [],
      historyRange,
      historyStatus: "idle",
      historyWindow: null,
      historyError: null,
      setHistoryRange,
      retryHistory,
      error: null,
      retry,
    };
  }

  const resolvedView = view ?? {
    status: "connecting" as const,
    samples: [],
    freshSamples: [],
    lastCapturedAt: null,
    ageMs: null,
    rejectedFutureSamples: 0,
  };

  return {
    mode: "live",
    status: resolvedView.status,
    view: resolvedView,
    kpis: buildLiveDashboardKpis(resolvedView),
    temperatures: selectProductionTemperatures(resolvedView),
    historySamples: visibleHistory,
    historyRange,
    historyStatus: visibleHistoryStatus,
    historyWindow: visibleHistoryWindow,
    historyError: visibleHistoryError,
    setHistoryRange,
    retryHistory,
    error,
    retry,
  };
}
''',
)

write(
    "src/components/dashboard/temperature-chart.tsx",
    '''"use client";

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Clock3,
  LoaderCircle,
  Radio,
  RotateCcw,
  Settings2,
  Thermometer,
} from "lucide-react";

import { chartSeries } from "@/data/dashboard";
import type {
  DashboardHistoryRange,
  DashboardHistoryStatus,
} from "@/hooks/use-dashboard-telemetry";
import type { DashboardTelemetryStatus } from "@/lib/telemetry/dashboard-state";
import {
  buildTemperatureHistoryChart,
  mergeTelemetryHistory,
} from "@/lib/telemetry/history-series";
import type { TelemetrySample } from "@/lib/telemetry/types";

const demoRanges = ["1г", "6г", "24г", "7д", "30д"];
const liveRanges: Array<{ value: DashboardHistoryRange; label: string }> = [
  { value: "1h", label: "1г" },
  { value: "6h", label: "6г" },
  { value: "24h", label: "24г" },
];
const channelColors: Record<string, string> = {
  "106-03": "#00c6e0",
  "106-04": "#7ed321",
};

function createPath(points: readonly number[]) {
  return points
    .map((point, index) => {
      const x = 32 + (index / (points.length - 1)) * 568;
      const y = 162 - (point / 100) * 135;
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
}

function qualityLabel(sample: TelemetrySample): string {
  if (sample.quality === "sensor_error") return "Помилка датчика";
  if (sample.quality === "communication_error") return "Помилка зв’язку";
  if (sample.quality === "unknown") return "Невідома якість";
  return sample.alarm === null
    ? "Valid · без тривоги"
    : `Valid · ${sample.alarm === "high" ? "вище межі" : "нижче межі"}`;
}

function valueLabel(sample: TelemetrySample): string {
  if (sample.value === null || sample.quality !== "valid") return "—";
  return `${new Intl.NumberFormat("uk-UA", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(sample.value)} ${sample.unit}`;
}

function timeLabel(sample: TelemetrySample): string {
  return new Intl.DateTimeFormat("uk-UA", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(sample.captured_at));
}

function axisTime(value: string): string {
  return new Intl.DateTimeFormat("uk-UA", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function temperatureLabel(value: number | null): string {
  return value === null
    ? "—"
    : `${new Intl.NumberFormat("uk-UA", { maximumFractionDigits: 1 }).format(value)} °C`;
}

function LiveHistoryChart({
  latestSamples,
  historySamples,
  historyRange,
  historyStatus,
  historyWindow,
  historyError,
  onHistoryRangeChange,
  onHistoryRetry,
}: {
  latestSamples: TelemetrySample[];
  historySamples: TelemetrySample[];
  historyRange: DashboardHistoryRange;
  historyStatus: DashboardHistoryStatus;
  historyWindow: { from: string; to: string } | null;
  historyError: Error | null;
  onHistoryRangeChange: (range: DashboardHistoryRange) => void;
  onHistoryRetry: () => void;
}) {
  const fallbackTo = new Date();
  const fallbackFrom = new Date(
    fallbackTo.getTime() - (historyRange === "1h" ? 1 : historyRange === "6h" ? 6 : 24) * 60 * 60 * 1000,
  );
  const window = historyWindow ?? {
    from: fallbackFrom.toISOString(),
    to: fallbackTo.toISOString(),
  };
  const merged = useMemo(
    () => mergeTelemetryHistory(historySamples, latestSamples),
    [historySamples, latestSamples],
  );
  const chart = useMemo(
    () => buildTemperatureHistoryChart(merged, window),
    [merged, window.from, window.to],
  );

  return (
    <div className="mt-4 rounded-2xl border border-white/[0.055] bg-[#071a35]/60 p-3">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[10px] font-medium text-slate-200">PostgreSQL history</p>
          <p className="mt-0.5 text-[9px] text-slate-500">
            {axisTime(chart.from)} — {axisTime(chart.to)} · {merged.length} records
          </p>
        </div>
        <div className="flex items-center gap-1 rounded-xl border border-white/[0.06] bg-black/10 p-1">
          {liveRanges.map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => onHistoryRangeChange(item.value)}
              className={`rounded-lg px-2.5 py-1.5 text-[9px] font-medium transition ${
                historyRange === item.value
                  ? "bg-blue-600 text-white shadow-[0_5px_15px_rgba(0,119,255,.2)]"
                  : "text-slate-500 hover:text-slate-200"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {historyStatus === "loading" ? (
        <div className="grid h-[190px] place-items-center text-[10px] text-cyan-200">
          <span className="inline-flex items-center gap-2">
            <LoaderCircle className="h-4 w-4 animate-spin" />
            Завантаження захищеної історії…
          </span>
        </div>
      ) : historyStatus === "error" ? (
        <div className="grid h-[190px] place-items-center text-center">
          <div>
            <AlertTriangle className="mx-auto h-5 w-5 text-amber-300" />
            <p className="mt-2 text-[10px] text-amber-200">
              {historyError?.message ?? "Не вдалося завантажити telemetry history."}
            </p>
            <button
              type="button"
              onClick={onHistoryRetry}
              className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-[9px] text-slate-200"
            >
              <RotateCcw className="h-3 w-3" />
              Повторити
            </button>
          </div>
        </div>
      ) : chart.series.length === 0 ? (
        <div className="grid h-[190px] place-items-center text-center text-[10px] leading-5 text-slate-500">
          Немає валідних температурних records у вибраному діапазоні.
        </div>
      ) : (
        <>
          <svg
            viewBox="0 0 630 180"
            className="h-[190px] w-full"
            role="img"
            aria-label="Реальний графік історії температур XJP60D"
          >
            {[20, 47, 74, 101, 128, 155].map((y) => (
              <line
                key={y}
                x1="32"
                y1={y}
                x2="600"
                y2={y}
                stroke="rgba(148,163,184,.1)"
                strokeWidth="1"
              />
            ))}
            {[32, 174, 316, 458, 600].map((x) => (
              <line
                key={x}
                x1={x}
                y1="20"
                x2={x}
                y2="155"
                stroke="rgba(148,163,184,.055)"
                strokeWidth="1"
              />
            ))}
            {chart.series.map((series) => (
              <g key={series.channelId}>
                {series.path ? (
                  <path
                    d={series.path}
                    fill="none"
                    stroke={channelColors[series.channelId] ?? "#38bdf8"}
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                ) : null}
                {series.points.map((point) => (
                  <circle
                    key={point.eventId}
                    cx={point.x}
                    cy={point.y}
                    r="2.2"
                    fill="#071a35"
                    stroke={channelColors[series.channelId] ?? "#38bdf8"}
                    strokeWidth="1.4"
                  />
                ))}
              </g>
            ))}
            <text x="32" y="174" fill="#64748b" fontSize="9">
              {axisTime(chart.from)}
            </text>
            <text x="600" y="174" textAnchor="end" fill="#64748b" fontSize="9">
              {axisTime(chart.to)}
            </text>
            <text x="24" y="25" textAnchor="end" fill="#64748b" fontSize="9">
              {temperatureLabel(chart.maximum)}
            </text>
            <text x="24" y="155" textAnchor="end" fill="#64748b" fontSize="9">
              {temperatureLabel(chart.minimum)}
            </text>
          </svg>
          <div className="mt-2 flex flex-wrap gap-2">
            {chart.series.map((series) => (
              <span
                key={series.channelId}
                className="inline-flex items-center gap-1.5 rounded-full border border-white/[0.06] px-2 py-1 text-[8px] text-slate-400"
              >
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: channelColors[series.channelId] ?? "#38bdf8" }}
                />
                {series.channelId} · {series.points.length}
              </span>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function LiveTemperatureView({
  status,
  samples,
  historySamples,
  historyRange,
  historyStatus,
  historyWindow,
  historyError,
  onHistoryRangeChange,
  onHistoryRetry,
}: {
  status: DashboardTelemetryStatus;
  samples: TelemetrySample[];
  historySamples: TelemetrySample[];
  historyRange: DashboardHistoryRange;
  historyStatus: DashboardHistoryStatus;
  historyWindow: { from: string; to: string } | null;
  historyError: Error | null;
  onHistoryRangeChange: (range: DashboardHistoryRange) => void;
  onHistoryRetry: () => void;
}) {
  const byChannel = new Map(samples.map((sample) => [sample.channel_id, sample]));
  const channels = ["106-03", "106-04"];

  return (
    <div className="p-4 sm:p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[10px] tracking-[0.14em] text-cyan-300 uppercase">Production telemetry</p>
          <p className="mt-1 text-[11px] text-slate-400">
            XJP60D · edge-01 · authenticated latest, WebSocket та PostgreSQL history
          </p>
        </div>
        <span className="rounded-full border border-white/[0.07] bg-white/[0.025] px-3 py-1.5 text-[9px] text-slate-300">
          {status}
        </span>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {channels.map((channelId) => {
          const sample = byChannel.get(channelId);
          const hasError = sample !== undefined && sample.quality !== "valid";
          const hasAlarm = sample?.alarm !== null && sample?.alarm !== undefined;

          return (
            <article
              key={channelId}
              className={`rounded-2xl border p-4 ${
                hasError || hasAlarm
                  ? "border-red-300/15 bg-red-400/[0.045]"
                  : "border-cyan-300/10 bg-[#071a35]/70"
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <span className="grid h-10 w-10 place-items-center rounded-xl border border-white/[0.07] bg-white/[0.025] text-cyan-300">
                    {hasError || hasAlarm ? (
                      <AlertTriangle className="h-4 w-4 text-red-300" />
                    ) : (
                      <Thermometer className="h-4 w-4" />
                    )}
                  </span>
                  <div>
                    <p className="text-[10px] font-semibold text-white">{channelId}</p>
                    <p className="mt-0.5 text-[9px] text-slate-500">XJP60D Unit 106</p>
                  </div>
                </div>
                <span className="rounded-full border border-white/[0.06] bg-black/10 px-2 py-1 text-[8px] text-slate-400">
                  {sample?.quality ?? "no_data"}
                </span>
              </div>

              <p className="mt-5 text-3xl font-semibold tracking-tight text-white">
                {sample === undefined ? "—" : valueLabel(sample)}
              </p>
              <p
                className={`mt-2 text-[10px] font-medium ${
                  hasError || hasAlarm ? "text-red-300" : "text-emerald-300"
                }`}
              >
                {sample === undefined ? "Немає telemetry record" : qualityLabel(sample)}
              </p>
              <div className="mt-3 flex items-center gap-1.5 text-[9px] text-slate-500">
                <Clock3 className="h-3 w-3" />
                {sample === undefined ? "captured_at —" : `captured_at ${timeLabel(sample)}`}
              </div>
            </article>
          );
        })}
      </div>

      <LiveHistoryChart
        latestSamples={samples}
        historySamples={historySamples}
        historyRange={historyRange}
        historyStatus={historyStatus}
        historyWindow={historyWindow}
        historyError={historyError}
        onHistoryRangeChange={onHistoryRangeChange}
        onHistoryRetry={onHistoryRetry}
      />

      <div className="mt-3 flex items-start gap-2 rounded-xl border border-white/[0.055] bg-white/[0.018] p-3 text-[9px] leading-5 text-slate-500">
        <Radio className="mt-0.5 h-3.5 w-3.5 shrink-0 text-cyan-400" />
        Latest/WebSocket freshness та history loading мають незалежні стани. Історичний збій не маскує свіжий live record.
      </div>
    </div>
  );
}

export function TemperatureChart({
  mode = "demo",
  status = "demo",
  samples = [],
  historySamples = [],
  historyRange = "24h",
  historyStatus = "idle",
  historyWindow = null,
  historyError = null,
  onHistoryRangeChange = () => undefined,
  onHistoryRetry = () => undefined,
}: {
  mode?: "demo" | "live";
  status?: DashboardTelemetryStatus;
  samples?: TelemetrySample[];
  historySamples?: TelemetrySample[];
  historyRange?: DashboardHistoryRange;
  historyStatus?: DashboardHistoryStatus;
  historyWindow?: { from: string; to: string } | null;
  historyError?: Error | null;
  onHistoryRangeChange?: (range: DashboardHistoryRange) => void;
  onHistoryRetry?: () => void;
}) {
  const [range, setRange] = useState("24г");
  const paths = useMemo(
    () => chartSeries.map((series) => ({ ...series, path: createPath(series.points) })),
    [],
  );

  if (mode === "live") {
    return (
      <LiveTemperatureView
        status={status}
        samples={samples}
        historySamples={historySamples}
        historyRange={historyRange}
        historyStatus={historyStatus}
        historyWindow={historyWindow}
        historyError={historyError}
        onHistoryRangeChange={onHistoryRangeChange}
        onHistoryRetry={onHistoryRetry}
      />
    );
  }

  return (
    <div className="p-4 sm:p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[10px] tracking-[0.14em] text-blue-300 uppercase">Demo telemetry</p>
          <p className="mt-1 text-[11px] text-slate-400">Ізольований preview · не production measurements</p>
        </div>
        <div className="flex items-center gap-1 rounded-xl border border-white/[0.06] bg-black/10 p-1">
          {demoRanges.map((item) => (
            <button
              key={item}
              onClick={() => setRange(item)}
              className={`rounded-lg px-2.5 py-1.5 text-[9px] font-medium transition ${
                range === item
                  ? "bg-blue-600 text-white shadow-[0_5px_15px_rgba(0,119,255,.2)]"
                  : "text-slate-500 hover:text-slate-200"
              }`}
            >
              {item}
            </button>
          ))}
          <button
            className="ml-1 grid h-7 w-7 place-items-center rounded-lg text-slate-500 transition hover:bg-white/[0.05] hover:text-slate-200"
            aria-label="Налаштування графіка"
          >
            <Settings2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-white/[0.045] bg-[#071a35]/60 p-2">
        <svg
          viewBox="0 0 630 190"
          className="h-[200px] w-full"
          role="img"
          aria-label="Демонстраційний графік температур"
        >
          <defs>
            <linearGradient id="chartFade" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor="#0077ff" stopOpacity="0.13" />
              <stop offset="1" stopColor="#0077ff" stopOpacity="0" />
            </linearGradient>
            <filter id="softGlow" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="1.8" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>
          {[28, 55, 82, 109, 136, 163].map((y) => (
            <line key={y} x1="32" y1={y} x2="600" y2={y} stroke="rgba(148,163,184,.11)" strokeWidth="1" />
          ))}
          {[32, 145, 258, 371, 484, 600].map((x) => (
            <line key={x} x1={x} y1="20" x2={x} y2="163" stroke="rgba(148,163,184,.055)" strokeWidth="1" />
          ))}
          <path d={`${paths[2].path} L600 163 L32 163 Z`} fill="url(#chartFade)" />
          {paths.map((series) => (
            <g key={series.id} filter="url(#softGlow)">
              <path
                d={series.path}
                fill="none"
                stroke={series.color}
                strokeWidth="1.9"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              {[0, 5, 10, 15, 20, 23].map((index) => {
                const x = 32 + (index / 23) * 568;
                const y = 162 - (series.points[index] / 100) * 135;
                return (
                  <circle
                    key={index}
                    cx={x}
                    cy={y}
                    r="2.1"
                    fill="#071a35"
                    stroke={series.color}
                    strokeWidth="1.4"
                  />
                );
              })}
            </g>
          ))}
          {["00:00", "04:00", "08:00", "12:00", "16:00", "24:00"].map((label, index) => (
            <text
              key={label}
              x={32 + index * 113.6}
              y="181"
              textAnchor={index === 0 ? "start" : index === 5 ? "end" : "middle"}
              fill="#64748b"
              fontSize="9"
            >
              {label}
            </text>
          ))}
          {["20", "10", "0", "−10", "−20", "−30"].map((label, index) => (
            <text key={label} x="24" y={31 + index * 27} textAnchor="end" fill="#64748b" fontSize="9">
              {label}
            </text>
          ))}
        </svg>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {chartSeries.map((series) => (
          <button
            key={series.id}
            className="rounded-xl border border-white/[0.055] bg-white/[0.018] p-2.5 text-left transition hover:border-white/[0.1] hover:bg-white/[0.03]"
          >
            <div className="flex items-center gap-1.5 text-[9px] text-slate-500">
              <span className="h-2 w-2 rounded-[3px]" style={{ backgroundColor: series.color }} />
              {series.id}
            </div>
            <p className="mt-1.5 text-lg font-medium tracking-tight text-slate-100">{series.value}</p>
          </button>
        ))}
      </div>
    </div>
  );
}
''',
)

path = "src/components/dashboard/dashboard-shell.tsx"
content = read(path)
old = '''                <TemperatureChart
                  mode={telemetry.mode}
                  status={telemetry.status}
                  samples={telemetry.temperatures}
                />'''
new = '''                <TemperatureChart
                  mode={telemetry.mode}
                  status={telemetry.status}
                  samples={telemetry.temperatures}
                  historySamples={telemetry.historySamples}
                  historyRange={telemetry.historyRange}
                  historyStatus={telemetry.historyStatus}
                  historyWindow={telemetry.historyWindow}
                  historyError={telemetry.historyError}
                  onHistoryRangeChange={telemetry.setHistoryRange}
                  onHistoryRetry={telemetry.retryHistory}
                />'''
if old not in content:
    raise RuntimeError("Dashboard temperature chart call was not found")
write(path, content.replace(old, new, 1))

write(
    "src/hooks/use-dashboard-telemetry.test.ts",
    '''import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TelemetryHistoryQuery, TelemetryLiveHandlers, TelemetrySample } from "@/lib/telemetry/types";

const adapterState = vi.hoisted(() => ({
  latest: vi.fn(),
  history: vi.fn(),
  subscribe: vi.fn(),
  handlers: null as unknown,
}));

vi.mock("@/lib/telemetry/runtime-config", () => ({
  getTelemetryRuntimeConfig: () => ({
    mode: "live",
    apiBaseUrl: "http://127.0.0.1:8082",
    websocketUrl: "ws://127.0.0.1:8082/api/v1/telemetry/live",
  }),
}));

vi.mock("@/lib/telemetry/create-adapter", () => ({
  createTelemetryAdapter: () => ({
    readiness: vi.fn(),
    history: adapterState.history,
    latest: adapterState.latest,
    subscribe: adapterState.subscribe,
  }),
}));

import { useDashboardTelemetry } from "./use-dashboard-telemetry";

const sample: TelemetrySample = {
  event_id: "recovered-event",
  node_id: "edge-01",
  captured_at: new Date().toISOString(),
  metric: "temperature.probe",
  value: 4.2,
  unit: "degC",
  quality: "valid",
  source: "modbus",
  equipment_id: "xjp60d-106",
  channel_id: "106-03",
  alarm: null,
  raw_value: 42,
  raw_status: null,
};

describe("useDashboardTelemetry", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    adapterState.handlers = null;

    adapterState.latest.mockResolvedValue({
      items: [],
      count: 0,
      limit: 1000,
      offset: 0,
      next_offset: null,
    });
    adapterState.history.mockResolvedValue({
      items: [sample],
      count: 1,
      limit: 1000,
      offset: 0,
      next_offset: null,
    });
    adapterState.subscribe.mockImplementation((_filters: unknown, handlers: TelemetryLiveHandlers) => {
      adapterState.handlers = handlers;
      return { close: vi.fn() };
    });
  });

  it("clears transient transport errors after reconnect and a committed sample", async () => {
    const { result } = renderHook(() => useDashboardTelemetry());

    await waitFor(() => {
      expect(adapterState.subscribe).toHaveBeenCalledOnce();
    });

    const handlers = adapterState.handlers as TelemetryLiveHandlers;

    act(() => {
      handlers.onError?.(new Error("Telemetry WebSocket transport error"));
    });

    await waitFor(() => {
      expect(result.current.error?.message).toBe("Telemetry WebSocket transport error");
    });

    act(() => {
      handlers.onStateChange?.("connected");
    });

    await waitFor(() => {
      expect(result.current.error).toBeNull();
    });

    act(() => {
      handlers.onError?.(new Error("Temporary reconnect error"));
    });

    await waitFor(() => {
      expect(result.current.error?.message).toBe("Temporary reconnect error");
    });

    act(() => {
      handlers.onSample(sample);
    });

    await waitFor(() => {
      expect(result.current.error).toBeNull();
      expect(result.current.status).toBe("live");
    });
  });

  it("loads authenticated history and reloads the selected time range", async () => {
    const { result } = renderHook(() =>
      useDashboardTelemetry({ enabled: true, organizationId: "org-1" }),
    );

    await waitFor(() => {
      expect(result.current.historyStatus).toBe("ready");
      expect(result.current.historySamples).toEqual([sample]);
    });

    const firstQuery = adapterState.history.mock.calls[0][0] as TelemetryHistoryQuery;
    expect(firstQuery.node_id).toBe("edge-01");
    expect(firstQuery.metric).toBe("temperature.probe");
    expect(new Date(firstQuery.to).getTime() - new Date(firstQuery.from).getTime()).toBe(24 * 60 * 60 * 1000);

    act(() => {
      result.current.setHistoryRange("1h");
    });

    await waitFor(() => {
      expect(adapterState.history).toHaveBeenCalledTimes(2);
      expect(result.current.historyRange).toBe("1h");
    });
    const secondQuery = adapterState.history.mock.calls[1][0] as TelemetryHistoryQuery;
    expect(new Date(secondQuery.to).getTime() - new Date(secondQuery.from).getTime()).toBe(60 * 60 * 1000);
  });

  it("hides history immediately when the organization scope changes", async () => {
    const { result, rerender } = renderHook(
      ({ organizationId }) => useDashboardTelemetry({ enabled: true, organizationId }),
      { initialProps: { organizationId: "org-1" } },
    );
    await waitFor(() => expect(result.current.historyStatus).toBe("ready"));

    rerender({ organizationId: "org-2" });
    expect(result.current.historySamples).toEqual([]);
    expect(result.current.historyStatus).toBe("loading");
  });
});
''',
)

path = "docs/authenticated-live-telemetry.md"
content = read(path)
marker = "## Required public frontend variables\n"
section = '''## Authenticated history\n\nThe temperature panel queries `/api/v1/telemetry/history` independently from the latest snapshot and WebSocket connection. Operators can select 1-hour, 6-hour and 24-hour windows. History errors have their own retry state and do not downgrade a fresh live connection.\n\nHistory and latest records are deduplicated by immutable event ID before rendering. Only valid production temperature channels are plotted; sensor and communication errors remain available in current-state cards but are not rendered as numeric curve points.\n\n'''
if marker not in content:
    raise RuntimeError("History documentation marker was not found")
write(path, content.replace(marker, section + marker, 1))
