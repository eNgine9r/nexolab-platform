"use client";

import { createReconnectBackfillObserver } from "@/lib/telemetry/reconnect-backfill";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  CADENCE_OBSERVATION_LIMIT,
  EMPTY_CADENCE_OBSERVATIONS,
  isLiveSampleFresh,
  liveFreshnessFor,
  recordCadenceObservation,
  seedCadenceObservations,
  type CadenceObservations,
} from "@/features/live/freshness";
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
import {
  appendIntervalSample,
  computeIntervalStatistics,
  createIntervalSampleColumns,
  pruneIntervalSamplesBefore,
  type IntervalSampleColumns,
  type IntervalStatistics,
} from "@/features/charts/interval-statistics";
import { savedDashboardDisplaySample } from "@/features/live-dashboards/embraco-series";
import { getDisplayTimeZone } from "@/features/display-time/store";
import { dashboardItemIdentity } from "@/features/live-dashboards/model";
import { resolveViewSettings } from "@/features/live-dashboards/view-settings";
import {
  appendSavedDashboardTail,
  operatorHistoryPreview,
  reduceSavedDashboardHistory,
  restoreOperatorEvidence,
} from "@/features/live-dashboards/operator-history";
import type {
  LiveDashboard,
  LiveDashboardItem,
  LiveDashboardSeries,
  LiveDashboardTelemetryStatus,
} from "@/features/live-dashboards/types";
import {
  advanceLiveHistoryWindow,
  advanceWindowToClock,
  deriveLiveSourceGapMsByChannel,
} from "@/features/live/live-history";
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

function dashboardSeriesQuery(item: LiveDashboardItem) {
  return {
    channel_id: item.channel_id,
    metric: item.metric,
    ...(item.channel_ref_id === null
      ? { node_id: item.node_id ?? "", equipment_id: item.equipment_id ?? "" }
      : {}),
  };
}

function dashboardSeriesMatches(item: LiveDashboardItem, sample: TelemetrySample) {
  return (
    item.channel_id === sample.channel_id &&
    item.metric === sample.metric &&
    (item.channel_ref_id !== null ||
      (item.node_id === sample.node_id && item.equipment_id === sample.equipment_id))
  );
}

const RENDERED_POINTS_PER_SERIES = 240;
const DEFAULT_SCOPE = "__default_organization__";

interface RuntimeResult {
  config: TelemetryRuntimeConfig | null;
  error: Error | null;
}

export type LiveDashboardHistoryStatus = "idle" | "loading" | "ready" | "error";
export type LiveDashboardExportStatus = "idle" | "exporting" | "error";

/** Exact statistics for [fromMs, toMs] of one dashboard item, from raw persisted samples (#1645). */
export type LiveDashboardIntervalStatistics = (
  itemIdentity: string,
  fromMs: number,
  toMs: number,
) => IntervalStatistics | null;

export interface LiveDashboardTelemetryModel {
  status: LiveDashboardTelemetryStatus;
  connectionState: TelemetryConnectionState;
  series: LiveDashboardSeries[];
  lastCapturedAt: string | null;
  /** Per-series observed acquisition cadence keyed by dashboard item identity (#1522). */
  cadenceObservations?: CadenceObservations;
  /** Wall-clock tick (epoch ms) used for freshness, so a silent series goes stale without a new sample (#1643). */
  now?: number;
  /** Raw-sample interval statistics provider; results change only when `series` changes. */
  intervalStatistics?: LiveDashboardIntervalStatistics;
  /** Raw measurement columns of one item (for exact digital state lanes, #1679); recompute when `series` changes. */
  intervalColumns?: (itemIdentity: string) => IntervalSampleColumns | undefined;
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

/** Records raw samples (pre-reduction) with the operator-visible display value (#1645). */
function recordIntervalSamples(
  store: Record<string, IntervalSampleColumns>,
  key: string,
  item: LiveDashboardItem,
  samples: readonly TelemetrySample[],
): void {
  const columns = (store[key] ??= createIntervalSampleColumns());
  for (const sample of samples) {
    const display = savedDashboardDisplaySample(item, sample);
    appendIntervalSample(columns, Date.parse(sample.captured_at), display ? display.value : null);
  }
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
  item: LiveDashboardItem,
  samples: readonly TelemetrySample[],
  window: TelemetryHistoryWindow,
  maximumPoints: number,
): TelemetrySample[] {
  const fromMs = window.from.getTime();
  const toMs = window.to.getTime();
  return reduceSavedDashboardHistory(
    item,
    samples.filter((sample) => {
      const capturedAt = sampleTimestamp(sample);
      return capturedAt >= fromMs && capturedAt <= toMs;
    }),
    window,
    maximumPoints,
  );
}

function deriveStatus(
  connectionState: TelemetryConnectionState,
  loaded: boolean,
  entries: ReadonlyArray<{ key: string; sample: TelemetrySample }>,
  cadence: CadenceObservations,
  error: Error | null,
  now: number,
): LiveDashboardTelemetryStatus {
  const samples = entries.map((entry) => entry.sample);
  if (connectionState === "unauthorized") return "unauthorized";
  if (connectionState === "forbidden") return "forbidden";
  if (connectionState === "configuration_error") return "configuration_error";
  if (!loaded && samples.length === 0) return error ? "error" : "connecting";
  if (connectionState === "reconnecting") return "reconnecting";
  if (connectionState === "offline" || connectionState === "idle") return "offline";
  if (error && samples.length === 0) return "error";
  const hasFresh = entries.some(({ key, sample }) =>
    isLiveSampleFresh(sample, now, liveFreshnessFor(sample, key, cadence)),
  );
  return hasFresh ? "live" : "stale";
}

/**
 * The range a dashboard opens with. A saved analysis view (#1666) wins over the dashboard default:
 * this reset runs after the live view mounted, so it must not overwrite the restored range.
 */
function openingHistoryRange(dashboard: LiveDashboard): LiveDashboardHistoryRange {
  const saved = resolveViewSettings(dashboard.view_settings, dashboard.items)?.range;
  if (saved?.kind === "preset") return liveDashboardPresetRange(saved.preset);
  if (saved?.kind === "custom") {
    try {
      return liveDashboardCustomRange(saved.from, saved.to);
    } catch {
      // An unusable stored period falls back to the dashboard default.
    }
  }
  return liveDashboardPresetRange(defaultLiveDashboardHistoryPreset(dashboard.time_window));
}

export function useLiveDashboardTelemetry({
  dashboard,
  organizationId,
  enabled,
  pointsPerSeries = RENDERED_POINTS_PER_SERIES,
}: {
  dashboard: LiveDashboard | null;
  organizationId: string | null;
  enabled: boolean;
  /** Maximum rendered points per series after the user-selected density (#1620). */
  pointsPerSeries?: number;
}): LiveDashboardTelemetryModel {
  const active = enabled && dashboard !== null && dashboard.status === "active";
  const scopeKey = active ? `${organizationId ?? DEFAULT_SCOPE}:${dashboard.id}:${dashboard.version}` : null;
  const [runtime] = useState<RuntimeResult>(runtimeResult);
  const [activeScopeKey, setActiveScopeKey] = useState<string | null>(null);
  const [latest, setLatest] = useState<Record<string, TelemetrySample>>({});
  const [cadence, setCadence] = useState<CadenceObservations>(EMPTY_CADENCE_OBSERVATIONS);
  const [history, setHistory] = useState<Record<string, TelemetrySample[]>>({});
  const [connectionState, setConnectionState] = useState<TelemetryConnectionState>("idle");
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<Error | null>(runtime.error);
  const [clock, setClock] = useState(Date.now);
  const [generation, setGeneration] = useState(0);
  const [historyGeneration, setHistoryGeneration] = useState(0);
  const [historyRange, setHistoryRange] = useState<LiveDashboardHistoryRange>(() =>
    dashboard ? openingHistoryRange(dashboard) : liveDashboardPresetRange("24h"),
  );
  const [historyWindow, setHistoryWindow] = useState<LiveDashboardHistoryRange>(historyRange);
  const [historyStatus, setHistoryStatus] = useState<LiveDashboardHistoryStatus>("idle");
  const [historyError, setHistoryError] = useState<Error | null>(null);
  const [exportStatus, setExportStatus] = useState<LiveDashboardExportStatus>("idle");
  const [exportError, setExportError] = useState<Error | null>(null);
  const latestRef = useRef<Record<string, TelemetrySample>>({});
  const cadenceRef = useRef<CadenceObservations>(EMPTY_CADENCE_OBSERVATIONS);
  const historyRef = useRef<Record<string, TelemetrySample[]>>({});
  const statsRef = useRef<Record<string, IntervalSampleColumns>>({});
  // #1805: continuity tolerance per series, derived once from the RAW history load, and channels
  // whose last live sample was not renderable (the next point starts a new segment).
  const sourceGapRef = useRef<Record<string, number>>({});
  const pendingBreaksRef = useRef<Set<string>>(new Set());
  const pointsPerSeriesRef = useRef(pointsPerSeries);
  const historyOrderingRef = useRef<TelemetryHistoryOrderingState | null>(null);
  const historyPendingLiveRef = useRef<TelemetrySample[]>([]);
  const historyWindowRef = useRef<TelemetryHistoryWindow>(rangeWindow(historyRange));
  const historySelectionRef = useRef<LiveDashboardHistoryRange>(historyRange);
  const renderTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const rangeScopeRef = useRef<string | null>(scopeKey);
  const historyKey = liveDashboardHistoryRangeKey(historyRange);

  // Declared before the history effect so a density change is visible to its reload.
  useEffect(() => {
    pointsPerSeriesRef.current = pointsPerSeries;
  }, [pointsPerSeries]);

  const flush = useCallback(() => {
    setLatest({ ...latestRef.current });
    setCadence(cadenceRef.current);
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
        // The CSV local-time column follows the operator's display time zone preference (#1658).
        timezone: getDisplayTimeZone(),
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
    const interval = globalThis.setInterval(() => {
      const now = Date.now();
      setClock(now);
      // Rolling ranges follow wall-clock time even when no sample arrives, so a silent
      // series visibly stops before "now" instead of looking live at the right edge.
      const selection = historySelectionRef.current;
      if (selection.kind === "custom") return;
      const current = historyWindowRef.current;
      const next = advanceWindowToClock(current, now);
      if (next === current) return;
      historyWindowRef.current = next;
      setHistoryWindow(serializedWindow(next, selection.kind, selection.label));
    }, 5_000);
    return () => globalThis.clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!active || !dashboard || scopeKey === null) {
      rangeScopeRef.current = null;
      return;
    }
    if (rangeScopeRef.current === scopeKey) return;
    rangeScopeRef.current = scopeKey;
    const nextRange = openingHistoryRange(dashboard);
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
      cadenceRef.current = EMPTY_CADENCE_OBSERVATIONS;
      historyRef.current = {};
      statsRef.current = {};
      historyOrderingRef.current = null;
      historyPendingLiveRef.current = [];
      return;
    }

    const controller = new AbortController();
    let disposed = false;
    latestRef.current = {};
    cadenceRef.current = EMPTY_CADENCE_OBSERVATIONS;

    void Promise.resolve().then(() => {
      if (disposed || controller.signal.aborted) return;
      setActiveScopeKey(scopeKey);
      setLatest({});
      setCadence(EMPTY_CADENCE_OBSERVATIONS);
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

    const commitHistoryTail = (key: string, item: LiveDashboardItem, sample: TelemetrySample) => {
      const ordering = historyOrderingRef.current;
      if (ordering === null) {
        historyPendingLiveRef.current.push(sample);
        return;
      }
      const reconciled = reconcileTelemetryHistoryEvents([operatorHistoryPreview(item, sample)], ordering);
      historyOrderingRef.current = reconciled.state;
      if (reconciled.samples.length === 0) return;
      const sourceSamples = restoreOperatorEvidence(reconciled.samples, [sample]);

      const selection = historySelectionRef.current;
      const currentWindow = historyWindowRef.current;
      const nextWindow =
        selection.kind === "custom" ? currentWindow : advanceLiveHistoryWindow(currentWindow, sourceSamples);
      historyWindowRef.current = nextWindow;
      recordIntervalSamples(statsRef.current, key, item, sourceSamples);
      if (selection.kind !== "custom") {
        const columns = statsRef.current[key];
        if (columns) pruneIntervalSamplesBefore(columns, nextWindow.from.getTime());
      }
      historyRef.current[key] = appendSavedDashboardTail(
        item,
        historyRef.current[key] ?? [],
        sourceSamples,
        nextWindow,
        pointsPerSeriesRef.current,
        sourceGapRef.current[key],
        pendingBreaksRef.current,
      );
      setHistoryWindow(serializedWindow(nextWindow, selection.kind, selection.label));
      scheduleFlush(dashboard.refresh_seconds);
    };

    const commitSample = (item: LiveDashboardItem, sample: TelemetrySample, immediate = false) => {
      if (!dashboardSeriesMatches(item, sample)) return;
      const key = dashboardItemIdentity(item);
      latestRef.current[key] = newestSample(latestRef.current[key], sample);
      cadenceRef.current = recordCadenceObservation(cadenceRef.current, key, sampleTimestamp(sample));
      commitHistoryTail(key, item, sample);
      scheduleFlush(dashboard.refresh_seconds, immediate || Object.keys(latestRef.current).length === 1);
    };

    // One subscription per item reconnects independently; coalesce their
    // recoveries into a single history reload for the current window.
    let backfillQueued = false;
    const requestBackfill = () => {
      if (backfillQueued) return;
      backfillQueued = true;
      setTimeout(() => {
        backfillQueued = false;
        if (!disposed) setHistoryGeneration((value) => value + 1);
      }, 1_000);
    };
    for (const item of dashboard.items) {
      const observeReconnect = createReconnectBackfillObserver(requestBackfill);
      subscriptions.push(
        adapter.subscribe(dashboardSeriesQuery(item), {
          onSample: (sample) => commitSample(item, sample),
          onStateChange: (state) => {
            if (disposed) return;
            setConnectionState(state);
            observeReconnect(state);
            if (state === "connected") setError(null);
          },
          onError: (nextError) => {
            if (!disposed) setError(nextError);
          },
          onHeartbeat: () => setClock(Date.now()),
        }),
      );
    }

    void Promise.all(
      dashboard.items.map(async (item) => {
        const response = await adapter.latest(
          { ...dashboardSeriesQuery(item), limit: 1, offset: 0 },
          controller.signal,
        );
        return { item, samples: response.items };
      }),
    )
      .then((pages) => {
        if (disposed) return;
        for (const { item, samples } of pages) for (const sample of samples) commitSample(item, sample, true);
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
      statsRef.current = {};
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
    statsRef.current = {};
    sourceGapRef.current = {};
    pendingBreaksRef.current = new Set();
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
          dashboardSeriesQuery(item),
          requestedWindow,
          { signal: controller.signal, snapshotAt },
        );
        snapshotAt = result.snapshotAt;
        const key = dashboardItemIdentity(item);
        const samples = result.samples.filter((sample) => dashboardSeriesMatches(item, sample));
        recordIntervalSamples(statsRef.current, key, item, samples);
        const rawGap = deriveLiveSourceGapMsByChannel(samples).values().next().value;
        if (rawGap !== undefined) sourceGapRef.current[key] = rawGap;
        reducedBySeries[key] = reduceHistory(item, samples, requestedWindow, pointsPerSeriesRef.current);
        if (requestedRange.kind !== "custom") {
          // #1522: raw (pre-reduction) persisted spacing bootstraps freshness.
          cadenceRef.current = seedCadenceObservations(
            cadenceRef.current,
            key,
            samples.slice(-CADENCE_OBSERVATION_LIMIT).map(sampleTimestamp),
          );
        }
        const tail = samples.at(-1);
        if (tail) {
          sourceTails.push(tail);
          latestRef.current[key] = newestSample(latestRef.current[key], tail);
        }
      }

      if (disposed) return;
      let ordering = seedTelemetryHistoryOrderingState(sourceTails);
      const pending = historyPendingLiveRef.current;
      const pendingPreview = pending.map((sample) => {
        const item = dashboard.items.find((candidate) => dashboardSeriesMatches(candidate, sample));
        return item ? operatorHistoryPreview(item, sample) : sample;
      });
      const reconciled = reconcileTelemetryHistoryEvents(pendingPreview, ordering);
      const restoredSamples = restoreOperatorEvidence(reconciled.samples, pending);
      ordering = reconciled.state;
      const finalWindow =
        requestedRange.kind === "custom"
          ? requestedWindow
          : advanceLiveHistoryWindow(requestedWindow, restoredSamples);

      for (const sample of restoredSamples) {
        for (const item of dashboard.items) {
          if (!dashboardSeriesMatches(item, sample)) continue;
          const key = dashboardItemIdentity(item);
          recordIntervalSamples(statsRef.current, key, item, [sample]);
          reducedBySeries[key] = appendSavedDashboardTail(
            item,
            reducedBySeries[key],
            [sample],
            finalWindow,
            pointsPerSeriesRef.current,
            sourceGapRef.current[key],
            pendingBreaksRef.current,
          );
          latestRef.current[key] = newestSample(latestRef.current[key], sample);
        }
      }

      historyPendingLiveRef.current = [];
      historyOrderingRef.current = ordering;
      historyWindowRef.current = finalWindow;
      historyRef.current = reducedBySeries;
      setLatest({ ...latestRef.current });
      setCadence(cadenceRef.current);
      setHistory({ ...reducedBySeries });
      setHistoryWindow(serializedWindow(finalWindow, requestedRange.kind, requestedRange.label));
      setHistoryStatus("ready");
      setHistoryError(null);
    })().catch((nextError: unknown) => {
      if (disposed || controller.signal.aborted) return;
      historyOrderingRef.current = null;
      historyPendingLiveRef.current = [];
      historyRef.current = {};
      statsRef.current = {};
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
    pointsPerSeries,
    runtime.config,
    scopeKey,
  ]);

  const storedSeries = useMemo<LiveDashboardSeries[]>(() => {
    if (!dashboard) return [];
    return dashboard.items.map((item) => {
      const key = dashboardItemIdentity(item);
      return { item, latest: latest[key] ?? null, history: history[key] ?? [], continuityAnnotated: true };
    });
  }, [dashboard, history, latest]);

  // Reads the raw column store; consumers recompute when `series` changes (every flush).
  const intervalStatistics = useCallback<LiveDashboardIntervalStatistics>((itemIdentity, fromMs, toMs) => {
    const columns = statsRef.current[itemIdentity];
    return columns ? computeIntervalStatistics(columns, fromMs, toMs) : null;
  }, []);

  const intervalColumns = useCallback(
    (itemIdentity: string): IntervalSampleColumns | undefined => statsRef.current[itemIdentity],
    [],
  );

  const visible = active && scopeKey !== null && activeScopeKey === scopeKey;
  const series = visible ? storedSeries : [];
  const entries = series.flatMap((item) =>
    item.latest ? [{ key: dashboardItemIdentity(item.item), sample: item.latest }] : [],
  );
  const samples = entries.map((entry) => entry.sample);
  const visibleCadence = visible ? cadence : EMPTY_CADENCE_OBSERVATIONS;
  const lastCapturedAt =
    [...samples].sort((left, right) => sampleTimestamp(right) - sampleTimestamp(left))[0]?.captured_at ??
    null;
  const visibleConnectionState = visible ? connectionState : active ? "connecting" : "idle";
  const visibleError = visible ? error : null;

  return {
    status: active
      ? deriveStatus(
          visibleConnectionState,
          visible ? loaded : false,
          entries,
          visibleCadence,
          visibleError,
          clock,
        )
      : "idle",
    connectionState: visibleConnectionState,
    series,
    lastCapturedAt,
    cadenceObservations: visibleCadence,
    now: clock,
    intervalStatistics,
    intervalColumns,
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
