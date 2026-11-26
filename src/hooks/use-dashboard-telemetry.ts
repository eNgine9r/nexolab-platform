"use client";

import { createReconnectBackfillObserver } from "@/lib/telemetry/reconnect-backfill";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { kpis as demoKpis } from "@/data/dashboard";
import {
  createOverviewHistoryStore,
  overviewDisplayHistory,
  overviewRecentTimestamps,
  overviewSourceGapMs,
  pruneOverviewHistory,
  recordOverviewSamples,
  type OverviewHistoryStore,
} from "@/features/dashboard/overview-history";
import { chartPointBudget } from "@/features/charts/point-budget";
import { createAuthenticatedFetch } from "@/features/security/security-session";
import { createRuntimeCredentialProvider } from "@/features/security/supabase-auth";
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
import {
  loadTelemetryHistorySlices,
  reconcileTelemetryHistoryEvents,
  seedTelemetryHistoryOrderingState,
  type TelemetryHistoryOrderingState,
  type TelemetryHistoryWindow,
} from "@/lib/telemetry/history";
import { getTelemetryRuntimeConfig } from "@/lib/telemetry/runtime-config";
import { advanceWindowToClock, appendLiveHistoryTail } from "@/features/live/live-history";
import {
  customHistoryRangeKey,
  resolveCustomHistoryWindow,
  type CustomHistoryWindow,
} from "@/features/charts/custom-history-range";
import {
  EMPTY_CADENCE_OBSERVATIONS,
  liveFreshnessFor,
  CADENCE_OBSERVATION_LIMIT,
  recordCadenceObservation,
  seedCadenceObservations,
  type CadenceObservations,
} from "@/features/live/freshness";
import { liveChannelKey } from "@/features/live/live-telemetry";
import { isTemperatureProbeSample } from "@/lib/telemetry/temperature-channel";
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
const HISTORY_HOURS = { "1h": 1, "6h": 6, "24h": 24, "7d": 7 * 24 } as const;
const HISTORY_PENDING_LIVE_LIMIT = 5_000;
/** Display points per Overview series; every raw measurement stays in the history columns. */
const OVERVIEW_DISPLAY_POINTS = chartPointBudget("overview");
/**
 * #1827: live history updates are coalesced — at most one per second up to 6 h, one per 5 s for
 * longer windows (a 24 h chart point spans minutes; series turn stale after 30 s at the earliest).
 */
function historyTailFlushMs(durationMs: number): number {
  return durationMs > 6 * 60 * 60 * 1_000 ? 5_000 : 1_000;
}

interface RuntimeConfigResult {
  config: TelemetryRuntimeConfig | null;
  error: Error | null;
}

interface DashboardHistoryTailContext {
  scopeKey: string;
  historyKey: string;
  durationMs: number;
  window: TelemetryHistoryWindow;
  /** A custom period (#1683): never advanced, never pruned, never extended by live samples. */
  fixed: boolean;
}

export type DashboardHistoryPreset = keyof typeof HISTORY_HOURS;
export type DashboardHistoryRange = DashboardHistoryPreset | "custom";
export type DashboardHistoryStatus = "idle" | "loading" | "ready" | "error";

export interface DashboardTelemetryOptions {
  enabled?: boolean;
  organizationId?: string | null;
  temperatureChannelIds?: readonly string[] | null;
}

export interface DashboardTelemetryModel {
  mode: "demo" | "live";
  status: DashboardTelemetryStatus;
  view: DashboardTelemetryView | null;
  kpis: readonly DashboardKpiValue[] | typeof demoKpis;
  temperatures: TelemetrySample[];
  /**
   * Continuity-annotated display history (extremum-preserving reduction plus the live tail). Every
   * RAW measurement is in `historyStore` (exact statistics, viewport detail); P0 charts 7 d / 30 d.
   */
  historySamples: TelemetrySample[];
  historyStore?: OverviewHistoryStore | null;
  /** Changes whenever `historyStore` changed (consumers recompute statistics and detail). */
  historyVersion?: number;
  historyRange: DashboardHistoryRange;
  historyStatus: DashboardHistoryStatus;
  historyWindow: { from: string; to: string } | null;
  historyError: Error | null;
  setHistoryRange: (range: DashboardHistoryPreset) => void;
  /**
   * Selects a fixed custom period (#1683). Throws an operator-facing Ukrainian message when the
   * period is invalid (start not before end, longer than 31 days, starting in the future).
   */
  applyCustomHistoryRange: (fromMs: number | null, toMs: number | null) => void;
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

function securedAdapter(config: TelemetryRuntimeConfig, organizationId: string | null): TelemetryAdapter {
  const credentialProvider = createRuntimeCredentialProvider(organizationId);
  return createTelemetryAdapter(config, {
    rest: {
      fetch: createAuthenticatedFetch(fetch.bind(globalThis), credentialProvider),
    },
    websocket: { credentials: credentialProvider },
  });
}

function advanceHistoryWindow(
  current: TelemetryHistoryWindow,
  incoming: readonly TelemetrySample[],
): TelemetryHistoryWindow {
  const durationMs = current.to.getTime() - current.from.getTime();
  let toMs = current.to.getTime();
  for (const sample of incoming) {
    const capturedAt = Date.parse(sample.captured_at);
    if (Number.isFinite(capturedAt) && capturedAt > toMs) toMs = capturedAt;
  }
  return toMs === current.to.getTime() ? current : { from: new Date(toMs - durationMs), to: new Date(toMs) };
}

function serializedHistoryWindow(window: TelemetryHistoryWindow): { from: string; to: string } {
  return { from: window.from.toISOString(), to: window.to.toISOString() };
}

export function useDashboardTelemetry(options: DashboardTelemetryOptions = {}): DashboardTelemetryModel {
  const enabled = options.enabled ?? true;
  const selectedOrganizationId = options.organizationId?.trim() || null;
  const scopeKey = enabled ? (selectedOrganizationId ?? DEFAULT_SCOPE) : null;
  const temperatureChannelKey =
    options.temperatureChannelIds === null || options.temperatureChannelIds === undefined
      ? null
      : [...new Set(options.temperatureChannelIds)].sort().join(",");
  const allowedTemperatureChannels = useMemo(
    () =>
      temperatureChannelKey === null
        ? null
        : new Set(temperatureChannelKey ? temperatureChannelKey.split(",") : []),
    [temperatureChannelKey],
  );
  const [runtime] = useState<RuntimeConfigResult>(loadRuntimeConfig);
  const [store, setStore] = useState<DashboardTelemetryStore>(createDashboardTelemetryStore);
  // #1634: per-channel acquisition cadence from raw (never chart-reduced) timestamps.
  const [cadence, setCadence] = useState<CadenceObservations>(EMPTY_CADENCE_OBSERVATIONS);
  const cadenceRef = useRef<CadenceObservations>(EMPTY_CADENCE_OBSERVATIONS);
  const [activeScopeKey, setActiveScopeKey] = useState<string | null>(scopeKey);
  const [connectionState, setConnectionState] = useState<TelemetryConnectionState>(() =>
    runtime.config?.mode === "live" ? "connecting" : "idle",
  );
  const [hasLoadedSnapshot, setHasLoadedSnapshot] = useState(false);
  const [error, setError] = useState<Error | null>(runtime.error);
  const [clock, setClock] = useState(() => Date.now());
  const [generation, setGeneration] = useState(0);
  const [historyRange, setHistoryRangeState] = useState<DashboardHistoryRange>("24h");
  const [customWindow, setCustomWindow] = useState<CustomHistoryWindow | null>(null);
  const setHistoryRange = useCallback((range: DashboardHistoryPreset) => setHistoryRangeState(range), []);
  const applyCustomHistoryRange = useCallback((fromMs: number | null, toMs: number | null) => {
    const next = resolveCustomHistoryWindow(fromMs, toMs);
    setCustomWindow(next);
    setHistoryRangeState("custom");
  }, []);
  const customFrom = historyRange === "custom" ? (customWindow?.from ?? null) : null;
  const customTo = historyRange === "custom" ? (customWindow?.to ?? null) : null;
  const [historySamples, setHistorySamples] = useState<TelemetrySample[]>([]);
  const historyStoreRef = useRef<OverviewHistoryStore | null>(null);
  const [historyStore, setHistoryStore] = useState<OverviewHistoryStore | null>(null);
  const [historyVersion, setHistoryVersion] = useState(0);
  // Channels whose last live sample was not renderable: their next point starts a new segment.
  const pendingBreaksRef = useRef<Set<string>>(new Set());
  const sourceGapMsFor = useCallback(
    (key: string) => overviewSourceGapMs(historyStoreRef.current?.columns[key]),
    [],
  );
  const [historyStatus, setHistoryStatus] = useState<DashboardHistoryStatus>(
    runtime.config?.mode === "live" ? "loading" : "idle",
  );
  const [historyWindow, setHistoryWindow] = useState<{ from: string; to: string } | null>(null);
  const [historyError, setHistoryError] = useState<Error | null>(null);
  const [activeHistoryKey, setActiveHistoryKey] = useState<string | null>(null);
  const [historyGeneration, setHistoryGeneration] = useState(0);
  const historyOrderingRef = useRef<TelemetryHistoryOrderingState | null>(null);
  const historyPendingLiveRef = useRef<TelemetrySample[]>([]);
  const historyTailContextRef = useRef<DashboardHistoryTailContext | null>(null);
  const tailBufferRef = useRef<TelemetrySample[]>([]);
  const tailTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (tailTimerRef.current !== null) globalThis.clearTimeout(tailTimerRef.current);
      tailTimerRef.current = null;
    },
    [],
  );
  const historyKey =
    scopeKey === null
      ? null
      : customFrom !== null && customTo !== null
        ? `${scopeKey}:${customHistoryRangeKey({ from: customFrom, to: customTo })}`
        : `${scopeKey}:${historyRange}`;

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

  const commitHistoryTail = useCallback(
    (incoming: readonly TelemetrySample[], expectedScopeKey: string) => {
      const temperatureSamples = incoming.filter(isTemperatureProbeSample);
      if (temperatureSamples.length === 0) return;

      const context = historyTailContextRef.current;
      if (!context || context.scopeKey !== expectedScopeKey) return;
      // A fixed custom period never receives live samples, before or after its history loads.
      if (context.fixed) return;

      const ordering = historyOrderingRef.current;
      if (ordering === null) {
        historyPendingLiveRef.current = [...historyPendingLiveRef.current, ...temperatureSamples].slice(
          -HISTORY_PENDING_LIVE_LIMIT,
        );
        return;
      }

      const reconciled = reconcileTelemetryHistoryEvents(temperatureSamples, ordering);
      historyOrderingRef.current = reconciled.state;
      if (reconciled.samples.length === 0) return;

      const nextWindow = advanceHistoryWindow(context.window, reconciled.samples);
      historyTailContextRef.current = { ...context, window: nextWindow };
      // #1827: live samples are coalesced (see historyTailFlushMs); deriving the Overview from raw
      // history per sample cost more than the sample interval at 24 h.
      tailBufferRef.current.push(...reconciled.samples);
      if (tailTimerRef.current !== null) return;
      tailTimerRef.current = globalThis.setTimeout(() => {
        tailTimerRef.current = null;
        const pending = tailBufferRef.current;
        tailBufferRef.current = [];
        const latestContext = historyTailContextRef.current;
        if (pending.length === 0 || !latestContext || latestContext.historyKey !== context.historyKey) return;
        const historyStore = historyStoreRef.current;
        if (historyStore) {
          recordOverviewSamples(historyStore, pending);
          pruneOverviewHistory(historyStore, latestContext.window.from.getTime());
        }
        setHistorySamples((current) =>
          appendLiveHistoryTail(current, pending, latestContext.window, OVERVIEW_DISPLAY_POINTS, {
            sourceGapMsFor,
            pendingBreakChannels: pendingBreaksRef.current,
          }),
        );
        setHistoryVersion((value) => value + 1);
        setHistoryWindow(serializedHistoryWindow(latestContext.window));
      }, historyTailFlushMs(context.durationMs));
    },
    [sourceGapMsFor],
  );

  useEffect(() => {
    const timer = window.setInterval(() => {
      const now = Date.now();
      setClock(now);
      // The Overview history window follows wall-clock time even when telemetry is silent,
      // so a stopped series ends visibly before "now" (chart audit 2026-11-21).
      const context = historyTailContextRef.current;
      if (!context || context.fixed) return;
      const nextWindow = advanceWindowToClock(context.window, now);
      if (nextWindow === context.window) return;
      historyTailContextRef.current = { ...context, window: nextWindow };
      if (historyStoreRef.current) pruneOverviewHistory(historyStoreRef.current, nextWindow.from.getTime());
      setHistorySamples((current) =>
        appendLiveHistoryTail(current, [], nextWindow, OVERVIEW_DISPLAY_POINTS, { sourceGapMsFor }),
      );
      setHistoryVersion((value) => value + 1);
      setHistoryWindow(serializedHistoryWindow(nextWindow));
    }, CLOCK_TICK_MS);
    return () => window.clearInterval(timer);
  }, [sourceGapMsFor]);

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
      cadenceRef.current = EMPTY_CADENCE_OBSERVATIONS;
      setCadence(EMPTY_CADENCE_OBSERVATIONS);
      setClock(Date.now());
    });

    const commit = (samples: readonly TelemetrySample[]) => {
      if (disposed) return;
      setStore((current) => mergeDashboardTelemetry(current, samples, { now: Date.now() }));
      let nextCadence = cadenceRef.current;
      for (const sample of samples) {
        nextCadence = recordCadenceObservation(
          nextCadence,
          liveChannelKey(sample),
          Date.parse(sample.captured_at),
        );
      }
      if (nextCadence !== cadenceRef.current) {
        cadenceRef.current = nextCadence;
        setCadence(nextCadence);
      }
      commitHistoryTail(samples, scopeKey);
      setError(null);
      setClock(Date.now());
    };

    const observeReconnect = createReconnectBackfillObserver(() => {
      if (!disposed) setHistoryGeneration((value) => value + 1);
    });
    const connectLive = () => {
      subscription = adapter.subscribe(
        {},
        {
          onSample: (sample) => commit([sample]),
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
        },
      );
    };

    void adapter
      .latest({ limit: 1000 }, controller.signal)
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
  }, [commitHistoryTail, enabled, generation, runtime.config, scopeKey, selectedOrganizationId]);

  useEffect(() => {
    const config = runtime.config;
    if (!config || config.mode === "demo" || !enabled || historyKey === null || scopeKey === null) return;

    const controller = new AbortController();
    const organizationId =
      selectedOrganizationId ?? process.env.NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID?.trim() ?? null;
    const fixed = historyRange === "custom";
    if (fixed && (customFrom === null || customTo === null)) return;
    const adapter = securedAdapter(config, organizationId);
    let requestedWindow: TelemetryHistoryWindow;
    if (fixed) {
      requestedWindow = { from: new Date(customFrom!), to: new Date(customTo!) };
    } else {
      const to = new Date();
      const from = new Date(to.getTime() - HISTORY_HOURS[historyRange] * 60 * 60 * 1000);
      requestedWindow = { from, to };
    }
    const durationMs = requestedWindow.to.getTime() - requestedWindow.from.getTime();
    let disposed = false;

    historyOrderingRef.current = null;
    historyPendingLiveRef.current = [];
    // A flush pending for the previous window must not consume the new window's samples.
    if (tailTimerRef.current !== null) globalThis.clearTimeout(tailTimerRef.current);
    tailTimerRef.current = null;
    tailBufferRef.current = [];
    pendingBreaksRef.current = new Set();
    historyStoreRef.current = null;
    historyTailContextRef.current = {
      scopeKey,
      historyKey,
      durationMs,
      window: requestedWindow,
      fixed,
    };

    void Promise.resolve().then(() => {
      if (disposed) return;
      setActiveHistoryKey(historyKey);
      setHistoryStatus("loading");
      setHistoryError(null);
      setHistorySamples([]);
      setHistoryStore(null);
      setHistoryWindow(serializedHistoryWindow(requestedWindow));
    });

    // P0 charts: the window loads as time slices (bounded parallelism, page retry, its own page
    // limit per slice, cancelled with the effect) into compact RAW columns; a window over the safe
    // raw row budget stops early with an explicit message instead of loading partially.
    const loadedStore = createOverviewHistoryStore();
    void loadTelemetryHistorySlices(
      adapter,
      { metric: "temperature.probe" },
      requestedWindow,
      { signal: controller.signal },
      (samples) => recordOverviewSamples(loadedStore, samples),
    )
      .then(() => {
        const context = historyTailContextRef.current;
        if (disposed || !context || context.historyKey !== historyKey) return;

        if (fixed) {
          // Exactly the requested window: no live tail, no advance, no cadence seeding from the past.
          historyPendingLiveRef.current = [];
          historyOrderingRef.current = null;
          historyStoreRef.current = loadedStore;
          setHistoryStore(loadedStore);
          setHistorySamples(overviewDisplayHistory(loadedStore, requestedWindow, OVERVIEW_DISPLAY_POINTS));
          setHistoryVersion((value) => value + 1);
          setHistoryWindow(serializedHistoryWindow(requestedWindow));
          setHistoryStatus("ready");
          setHistoryError(null);
          return;
        }
        // Raw persisted spacing bootstraps freshness before the live stream has seen two polls.
        let seeded = cadenceRef.current;
        for (const [key, columns] of Object.entries(loadedStore.columns)) {
          seeded = seedCadenceObservations(
            seeded,
            key,
            overviewRecentTimestamps(columns, CADENCE_OBSERVATION_LIMIT),
          );
        }
        if (seeded !== cadenceRef.current) {
          cadenceRef.current = seeded;
          setCadence(seeded);
        }
        const ordering = seedTelemetryHistoryOrderingState([...loadedStore.latest.values()]);
        const pending = historyPendingLiveRef.current;
        const reconciled = reconcileTelemetryHistoryEvents(pending, ordering);
        const finalWindow = advanceHistoryWindow(requestedWindow, reconciled.samples);
        // Display from the persisted columns first, then the live samples that arrived meanwhile.
        const persistedDisplay = overviewDisplayHistory(
          loadedStore,
          requestedWindow,
          OVERVIEW_DISPLAY_POINTS,
        );
        historyStoreRef.current = loadedStore;
        setHistoryStore(loadedStore);
        recordOverviewSamples(loadedStore, reconciled.samples);
        const combined = appendLiveHistoryTail(
          persistedDisplay,
          reconciled.samples,
          finalWindow,
          OVERVIEW_DISPLAY_POINTS,
          { sourceGapMsFor, pendingBreakChannels: pendingBreaksRef.current },
        );

        historyPendingLiveRef.current = [];
        historyOrderingRef.current = reconciled.state;
        historyTailContextRef.current = { ...context, window: finalWindow };
        setHistorySamples(combined);
        setHistoryVersion((value) => value + 1);
        setHistoryWindow(serializedHistoryWindow(finalWindow));
        setHistoryStatus("ready");
        setHistoryError(null);
      })
      .catch((nextError: unknown) => {
        if (controller.signal.aborted || disposed) return;
        historyStoreRef.current = null;
        setHistoryStore(null);
        historyOrderingRef.current = null;
        historyPendingLiveRef.current = [];
        setHistorySamples([]);
        setHistoryWindow(serializedHistoryWindow(requestedWindow));
        setHistoryStatus("error");
        setHistoryError(
          nextError instanceof Error ? nextError : new Error("Failed to load telemetry history"),
        );
      });

    return () => {
      disposed = true;
      controller.abort();
      if (historyTailContextRef.current?.historyKey === historyKey) {
        historyTailContextRef.current = null;
        historyOrderingRef.current = null;
        historyPendingLiveRef.current = [];
      }
    };
  }, [
    customFrom,
    customTo,
    enabled,
    historyGeneration,
    historyKey,
    historyRange,
    runtime.config,
    scopeKey,
    selectedOrganizationId,
    sourceGapMsFor,
  ]);

  const view = useMemo(() => {
    if (runtime.config?.mode !== "live" || !enabled || scopeKey === null || activeScopeKey !== scopeKey) {
      return null;
    }
    return deriveDashboardTelemetry(store, {
      now: clock,
      staleAfterMs: STALE_AFTER_MS,
      staleAfterMsFor: (sample) => liveFreshnessFor(sample, liveChannelKey(sample), cadence).staleAfterMs,
      hasLoadedSnapshot,
      connectionState,
      error,
    });
  }, [
    activeScopeKey,
    cadence,
    clock,
    connectionState,
    enabled,
    error,
    hasLoadedSnapshot,
    runtime.config,
    scopeKey,
    store,
  ]);

  const visibleHistory =
    activeHistoryKey === historyKey
      ? historySamples.filter(
          (sample) =>
            allowedTemperatureChannels === null || allowedTemperatureChannels.has(sample.channel_id),
        )
      : [];
  const visibleHistoryStatus = activeHistoryKey === historyKey ? historyStatus : "loading";
  const visibleHistoryWindow = activeHistoryKey === historyKey ? historyWindow : null;
  const visibleHistoryError = activeHistoryKey === historyKey ? historyError : null;

  if (!runtime.config) {
    return {
      mode: "live",
      status: "configuration_error",
      view: null,
      kpis: buildLiveDashboardKpis({
        status: "configuration_error",
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
      applyCustomHistoryRange,
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
      applyCustomHistoryRange,
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
    temperatures: selectProductionTemperatures(resolvedView).filter(
      (sample) => allowedTemperatureChannels === null || allowedTemperatureChannels.has(sample.channel_id),
    ),
    historySamples: visibleHistory,
    historyStore: activeHistoryKey === historyKey ? historyStore : null,
    historyVersion,
    historyRange,
    historyStatus: visibleHistoryStatus,
    historyWindow: visibleHistoryWindow,
    historyError: visibleHistoryError,
    setHistoryRange,
    applyCustomHistoryRange,
    retryHistory,
    error,
    retry,
  };
}
