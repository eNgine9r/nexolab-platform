"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  createLiveDashboardApiClient,
  type LiveDashboardCsvDownload,
} from "@/features/live-dashboards/api-client";
import {
  defaultLiveDashboardHistoryPreset,
  liveDashboardCustomRange,
  liveDashboardHistoryRangeKey,
  liveDashboardPresetRange,
  type LiveDashboardHistoryPreset,
  type LiveDashboardHistoryRange,
} from "@/features/live-dashboards/history-range";
import { dashboardItemIdentity } from "@/features/live-dashboards/model";
import type {
  LiveDashboard,
  LiveDashboardSeries,
  LiveDashboardTelemetryStatus,
} from "@/features/live-dashboards/types";
import { advanceLiveHistoryWindow, downsampleLiveHistory } from "@/features/live/live-history";
import { createRuntimeCredentialProvider } from "@/features/security/auth-runtime";
import { createAuthenticatedFetch } from "@/features/security/security-session";
import { createTelemetryAdapter } from "@/lib/telemetry/create-adapter";
import {
  loadCompleteTelemetryHistory,
  reconcileTelemetryHistoryEvents,
  seedTelemetryHistoryOrderingState,
  type TelemetryHistoryOrderingState,
  type TelemetryHistoryWindow,
} from "@/lib/telemetry/history";
import { getTelemetryRuntimeConfig } from "@/lib/telemetry/runtime-config";
import type {
  TelemetryAdapter,
  TelemetryConnectionState,
  TelemetryRuntimeConfig,
  TelemetrySample,
  TelemetrySubscription,
} from "@/lib/telemetry/types";

const STALE_AFTER_MS = 30_000;
const RENDERED_POINTS_PER_SERIES = 240;
const DEFAULT_SCOPE = "__default_organization__";

interface RuntimeResult {
  config: TelemetryRuntimeConfig | null;
  error: Error | null;
}

export type LiveDashboardHistoryStatus = "idle" | "loading" | "ready" | "error";
export type LiveDashboardExportStatus = "idle" | "exporting" | "error";

export interface LiveDashboardTelemetryModel {
  status: LiveDashboardTelemetryStatus;
  connectionState: TelemetryConnectionState;
  series: LiveDashboardSeries[];
  lastCapturedAt: string | null;
  historyRange: LiveDashboardHistoryRange;
  historyWindow: LiveDashboardHistoryRange;
  historyStatus: LiveDashboardHistoryStatus;
  historyError: Error | null;
  exportStatus: LiveDashboardExportStatus;
  exportError: Error | null;
  selectHistoryPreset: (preset: LiveDashboardHistoryPreset) => void;
  applyCustomHistoryRange: (from: Date | string, to: Date | string) => void;
  exportCsv: () => Promise<LiveDashboardCsvDownload>;
  error: Error | null;
  retry: () => void;
}

function runtimeResult(): RuntimeResult {
  try {
    return { config: getTelemetryRuntimeConfig(), error: null };
  } catch (error) {
    return {
      config: null,
      error: error instanceof Error ? error : new Error("Invalid telemetry configuration."),
    };
  }
}

function securedAdapter(config: TelemetryRuntimeConfig, organizationId: string | null): TelemetryAdapter {
  if (!config.apiBaseUrl) throw new Error("Telemetry API URL is unavailable.");
  const credentials = createRuntimeCredentialProvider(config.apiBaseUrl, organizationId);
  return createTelemetryAdapter(config, {
    rest: { fetch: createAuthenticatedFetch(fetch.bind(globalThis), credentials) },
    websocket: { credentials },
  });
}

function sampleTimestamp(sample: TelemetrySample): number {
  const value = Date.parse(sample.captured_at);
  return Number.isFinite(value) ? value : Number.NEGATIVE_INFINITY;
}

function newestSample(current: TelemetrySample | undefined, incoming: TelemetrySample): TelemetrySample {
  if (!current) return incoming;
  const capturedDifference = sampleTimestamp(incoming) - sampleTimestamp(current);
  if (capturedDifference > 0) return incoming;
  if (capturedDifference < 0) return current;
  const currentReceived = current.received_at ? Date.parse(current.received_at) : Number.NEGATIVE_INFINITY;
  const incomingReceived = incoming.received_at ? Date.parse(incoming.received_at) : Number.NEGATIVE_INFINITY;
  if (incomingReceived > currentReceived) return incoming;
  return incoming.event_id.localeCompare(current.event_id) > 0 ? incoming : current;
}

function rangeWindow(range: LiveDashboardHistoryRange): TelemetryHistoryWindow {
  return { from: new Date(range.from), to: new Date(range.to) };
}

function serializedWindow(
  window: TelemetryHistoryWindow,
  kind: LiveDashboardHistoryRange["kind"],
  label: string,
): LiveDashboardHistoryRange {
  return {
    kind,
    from: window.from.toISOString(),
    to: window.to.toISOString(),
    label,
  };
}

function reduceHistory(
  samples: readonly TelemetrySample[],
  window: TelemetryHistoryWindow,
): TelemetrySample[] {
  const fromMs = window.from.getTime();
  const toMs = window.to.getTime();
  return downsampleLiveHistory(
    samples.filter((sample) => {
      const capturedAt = sampleTimestamp(sample);
      return capturedAt >= fromMs && capturedAt <= toMs;
    }),
    window,
    RENDERED_POINTS_PER_SERIES,
  );
}

function deriveStatus(
  connectionState: TelemetryConnectionState,
  loaded: boolean,
  samples: readonly TelemetrySample[],
  error: Error | null,
  now: number,
): LiveDashboardTelemetryStatus {
  if (connectionState === "unauthorized") return "unauthorized";
  if (connectionState === "forbidden") return "forbidden";
  if (connectionState === "configuration_error") return "configuration_error";
  if (!loaded && samples.length === 0) return error ? "error" : "connecting";
  if (connectionState === "reconnecting") return "reconnecting";
  if (connectionState === "offline" || connectionState === "idle") return "offline";
  if (error && samples.length === 0) return "error";
  const hasFresh = samples.some((sample) => now - sampleTimestamp(sample) <= STALE_AFTER_MS);
  return hasFresh ? "live" : "stale";
}

export function useLiveDashboardTelemetry({
  dashboard,
  organizationId,
  enabled,
}: {
  dashboard: LiveDashboard | null;
  organizationId: string | null;
  enabled: boolean;
}): LiveDashboardTelemetryModel {
  const active = enabled && dashboard !== null && dashboard.status === "active";
  const scopeKey = active ? `${organizationId ?? DEFAULT_SCOPE}:${dashboard.id}:${dashboard.version}` : null;
  const [runtime] = useState<RuntimeResult>(runtimeResult);
  const [activeScopeKey, setActiveScopeKey] = useState<string | null>(null);
  const [latest, setLatest] = useState<Record<string, TelemetrySample>>({});
  const [history, setHistory] = useState<Record<string, TelemetrySample[]>>({});
  const [connectionState, setConnectionState] = useState<TelemetryConnectionState>("idle");
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<Error | null>(runtime.error);
  const [clock, setClock] = useState(Date.now);
  const [generation, setGeneration] = useState(0);
  const [historyGeneration, setHistoryGeneration] = useState(0);
  const [historyRange, setHistoryRange] = useState<LiveDashboardHistoryRange>(() =>
    liveDashboardPresetRange(dashboard ? defaultLiveDashboardHistoryPreset(dashboard.time_window) : "24h"),
  );
  const [historyWindow, setHistoryWindow] = useState<LiveDashboardHistoryRange>(historyRange);
  const [historyStatus, setHistoryStatus] = useState<LiveDashboardHistoryStatus>("idle");
  const [historyError, setHistoryError] = useState<Error | null>(null);
  const [exportStatus, setExportStatus] = useState<LiveDashboardExportStatus>("idle");
  const [exportError, setExportError] = useState<Error | null>(null);
  const latestRef = useRef<Record<string, TelemetrySample>>({});
  const historyRef = useRef<Record<string, TelemetrySample[]>>({});
  const historyOrderingRef = useRef<TelemetryHistoryOrderingState | null>(null);
  const historyPendingLiveRef = useRef<TelemetrySample[]>([]);
  const historyWindowRef = useRef<TelemetryHistoryWindow>(rangeWindow(historyRange));
  const historySelectionRef = useRef<LiveDashboardHistoryRange>(historyRange);
  const renderTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const rangeScopeRef = useRef<string | null>(scopeKey);
  const historyKey = liveDashboardHistoryRangeKey(historyRange);

  const flush = useCallback(() => {
    setLatest({ ...latestRef.current });
    setHistory({ ...historyRef.current });
    setClock(Date.now());
    renderTimerRef.current = null;
  }, []);

  const scheduleFlush = useCallback(
    (refreshSeconds: number, immediate = false) => {
      if (immediate) {
        if (renderTimerRef.current !== null) globalThis.clearTimeout(renderTimerRef.current);
        renderTimerRef.current = null;
        flush();
        return;
      }
      if (renderTimerRef.current !== null) return;
      renderTimerRef.current = globalThis.setTimeout(flush, refreshSeconds * 1_000);
    },
    [flush],
  );

  const retry = useCallback(() => {
    setError(null);
    setHistoryError(null);
    setLoaded(false);
    setConnectionState("connecting");
    setGeneration((value) => value + 1);
    setHistoryGeneration((value) => value + 1);
  }, []);

  const selectHistoryPreset = useCallback((preset: LiveDashboardHistoryPreset) => {
    setHistoryRange(liveDashboardPresetRange(preset));
    setHistoryGeneration((value) => value + 1);
  }, []);

  const applyCustomHistoryRange = useCallback((from: Date | string, to: Date | string) => {
    setHistoryRange(liveDashboardCustomRange(from, to));
    setHistoryGeneration((value) => value + 1);
  }, []);

  const exportCsv = useCallback(async (): Promise<LiveDashboardCsvDownload> => {
    if (!dashboard || !active) throw new Error("Saved Dashboard is not active.");
    setExportStatus("exporting");
    setExportError(null);
    try {
      const currentWindow = historyWindowRef.current;
      const download = await createLiveDashboardApiClient(organizationId).exportTelemetryCsv(dashboard.id, {
        from: currentWindow.from.toISOString(),
        to: currentWindow.to.toISOString(),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
      });
      setExportStatus("idle");
      return download;
    } catch (nextError) {
      const resolved = nextError instanceof Error ? nextError : new Error("CSV export failed.");
      setExportStatus("error");
      setExportError(resolved);
      throw resolved;
    }
  }, [active, dashboard, organizationId]);

  useEffect(() => {
    const interval = globalThis.setInterval(() => setClock(Date.now()), 5_000);
    return () => globalThis.clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!active || !dashboard || scopeKey === null) {
      rangeScopeRef.current = null;
      return;
    }
    if (rangeScopeRef.current === scopeKey) return;
    rangeScopeRef.current = scopeKey;
    const preset = defaultLiveDashboardHistoryPreset(dashboard.time_window);
    const nextRange = liveDashboardPresetRange(preset);
    historySelectionRef.current = nextRange;
    historyWindowRef.current = rangeWindow(nextRange);
    void Promise.resolve().then(() => {
      setHistoryRange(nextRange);
      setHistoryWindow(nextRange);
      setHistoryGeneration((value) => value + 1);
    });
  }, [active, dashboard, scopeKey]);

  useEffect(() => {
    const config = runtime.config;
    if (!active || !dashboard || scopeKey === null) {
      latestRef.current = {};
      historyRef.current = {};
      historyOrderingRef.current = null;
      historyPendingLiveRef.current = [];
      return;
    }

    const controller = new AbortController();
    let disposed = false;
    latestRef.current = {};

    void Promise.resolve().then(() => {
      if (disposed || controller.signal.aborted) return;
      setActiveScopeKey(scopeKey);
      setLatest({});
      setLoaded(false);
      if (!config || config.mode !== "live") {
        setError(runtime.error ?? new Error("Selected-series telemetry requires live mode."));
        setConnectionState("configuration_error");
        return;
      }
      setError(null);
      setConnectionState("connecting");
    });

    if (!config || config.mode !== "live") {
      return () => {
        disposed = true;
        controller.abort();
      };
    }

    const adapter = securedAdapter(config, organizationId);
    const subscriptions: TelemetrySubscription[] = [];
    const itemKeys = new Set(dashboard.items.map(dashboardItemIdentity));

    const commitHistoryTail = (sample: TelemetrySample) => {
      const ordering = historyOrderingRef.current;
      if (ordering === null) {
        historyPendingLiveRef.current.push(sample);
        return;
      }
      const reconciled = reconcileTelemetryHistoryEvents([sample], ordering);
      historyOrderingRef.current = reconciled.state;
      if (reconciled.samples.length === 0) return;

      const selection = historySelectionRef.current;
      const currentWindow = historyWindowRef.current;
      const nextWindow =
        selection.kind === "custom"
          ? currentWindow
          : advanceLiveHistoryWindow(currentWindow, reconciled.samples);
      historyWindowRef.current = nextWindow;
      const key = dashboardItemIdentity(sample);
      historyRef.current[key] = reduceHistory(
        [...(historyRef.current[key] ?? []), ...reconciled.samples],
        nextWindow,
      );
      setHistoryWindow(serializedWindow(nextWindow, selection.kind, selection.label));
      scheduleFlush(dashboard.refresh_seconds);
    };

    const commitSample = (sample: TelemetrySample, immediate = false) => {
      const key = dashboardItemIdentity(sample);
      if (!itemKeys.has(key)) return;
      latestRef.current[key] = newestSample(latestRef.current[key], sample);
      commitHistoryTail(sample);
      scheduleFlush(dashboard.refresh_seconds, immediate || Object.keys(latestRef.current).length === 1);
    };

    for (const item of dashboard.items) {
      subscriptions.push(
        adapter.subscribe(
          { channel_id: item.channel_id, metric: item.metric },
          {
            onSample: (sample) => commitSample(sample),
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
        ),
      );
    }

    void Promise.all(
      dashboard.items.map(async (item) => {
        const response = await adapter.latest(
          { channel_id: item.channel_id, metric: item.metric, limit: 1, offset: 0 },
          controller.signal,
        );
        return response.items;
      }),
    )
      .then((pages) => {
        if (disposed) return;
        for (const page of pages) for (const sample of page) commitSample(sample, true);
        setLoaded(true);
        scheduleFlush(dashboard.refresh_seconds, true);
      })
      .catch((nextError: unknown) => {
        if (disposed || controller.signal.aborted) return;
        setLoaded(true);
        setError(nextError instanceof Error ? nextError : new Error("Selected telemetry failed to load."));
        scheduleFlush(dashboard.refresh_seconds, true);
      });

    return () => {
      disposed = true;
      controller.abort();
      for (const subscription of subscriptions) subscription.close();
      if (renderTimerRef.current !== null) globalThis.clearTimeout(renderTimerRef.current);
      renderTimerRef.current = null;
    };
  }, [active, dashboard, generation, organizationId, runtime.config, runtime.error, scheduleFlush, scopeKey]);

  useEffect(() => {
    const config = runtime.config;
    if (!active || !dashboard || scopeKey === null || !config || config.mode !== "live") {
      historyRef.current = {};
      historyOrderingRef.current = null;
      historyPendingLiveRef.current = [];
      let disposed = false;
      void Promise.resolve().then(() => {
        if (!disposed) setHistoryStatus(active ? "error" : "idle");
      });
      return () => {
        disposed = true;
      };
    }

    const controller = new AbortController();
    let disposed = false;
    const requestedRange = historyRange;
    const requestedWindow = rangeWindow(requestedRange);
    historySelectionRef.current = requestedRange;
    historyWindowRef.current = requestedWindow;
    historyRef.current = {};
    historyOrderingRef.current = null;
    historyPendingLiveRef.current = [];

    void Promise.resolve().then(() => {
      if (disposed) return;
      setHistory({});
      setHistoryStatus("loading");
      setHistoryError(null);
      setHistoryWindow(requestedRange);
    });

    const adapter = securedAdapter(config, organizationId);
    void (async () => {
      let snapshotAt: string | undefined;
      const sourceTails: TelemetrySample[] = [];
      const reducedBySeries: Record<string, TelemetrySample[]> = {};

      for (const item of dashboard.items) {
        const result = await loadCompleteTelemetryHistory(
          adapter,
          { channel_id: item.channel_id, metric: item.metric },
          requestedWindow,
          { signal: controller.signal, snapshotAt },
        );
        snapshotAt = result.snapshotAt;
        const key = dashboardItemIdentity(item);
        reducedBySeries[key] = reduceHistory(result.samples, requestedWindow);
        const tail = result.samples.at(-1);
        if (tail) {
          sourceTails.push(tail);
          latestRef.current[key] = newestSample(latestRef.current[key], tail);
        }
      }

      if (disposed) return;
      let ordering = seedTelemetryHistoryOrderingState(sourceTails);
      const pending = historyPendingLiveRef.current;
      const reconciled = reconcileTelemetryHistoryEvents(pending, ordering);
      ordering = reconciled.state;
      const finalWindow =
        requestedRange.kind === "custom"
          ? requestedWindow
          : advanceLiveHistoryWindow(requestedWindow, reconciled.samples);

      for (const sample of reconciled.samples) {
        const key = dashboardItemIdentity(sample);
        if (!(key in reducedBySeries)) continue;
        reducedBySeries[key] = reduceHistory([...reducedBySeries[key], sample], finalWindow);
        latestRef.current[key] = newestSample(latestRef.current[key], sample);
      }

      historyPendingLiveRef.current = [];
      historyOrderingRef.current = ordering;
      historyWindowRef.current = finalWindow;
      historyRef.current = reducedBySeries;
      setLatest({ ...latestRef.current });
      setHistory({ ...reducedBySeries });
      setHistoryWindow(serializedWindow(finalWindow, requestedRange.kind, requestedRange.label));
      setHistoryStatus("ready");
      setHistoryError(null);
    })().catch((nextError: unknown) => {
      if (disposed || controller.signal.aborted) return;
      historyOrderingRef.current = null;
      historyPendingLiveRef.current = [];
      historyRef.current = {};
      setHistory({});
      setHistoryStatus("error");
      setHistoryError(
        nextError instanceof Error ? nextError : new Error("Saved Dashboard history failed to load."),
      );
    });

    return () => {
      disposed = true;
      controller.abort();
    };
  }, [
    active,
    dashboard,
    historyGeneration,
    historyKey,
    historyRange,
    organizationId,
    runtime.config,
    scopeKey,
  ]);

  const storedSeries = useMemo<LiveDashboardSeries[]>(() => {
    if (!dashboard) return [];
    return dashboard.items.map((item) => {
      const key = dashboardItemIdentity(item);
      return { item, latest: latest[key] ?? null, history: history[key] ?? [] };
    });
  }, [dashboard, history, latest]);

  const visible = active && scopeKey !== null && activeScopeKey === scopeKey;
  const series = visible ? storedSeries : [];
  const samples = series.flatMap((item) => (item.latest ? [item.latest] : []));
  const lastCapturedAt =
    [...samples].sort((left, right) => sampleTimestamp(right) - sampleTimestamp(left))[0]?.captured_at ??
    null;
  const visibleConnectionState = visible ? connectionState : active ? "connecting" : "idle";
  const visibleError = visible ? error : null;

  return {
    status: active
      ? deriveStatus(visibleConnectionState, visible ? loaded : false, samples, visibleError, clock)
      : "idle",
    connectionState: visibleConnectionState,
    series,
    lastCapturedAt,
    historyRange,
    historyWindow,
    historyStatus,
    historyError,
    exportStatus,
    exportError,
    selectHistoryPreset,
    applyCustomHistoryRange,
    exportCsv,
    error: visibleError,
    retry,
  };
}
