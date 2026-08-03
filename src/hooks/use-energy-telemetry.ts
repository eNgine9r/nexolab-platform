"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  loadCompleteEnergyHistory,
  mergeEnergyHistoryTail,
  selectEnergyHistoryTail,
} from "@/features/energy/energy-history";
import { reconcileEnergyLiveHistory } from "@/features/energy/energy-live-history";
import { createAuthenticatedFetch } from "@/features/security/security-session";
import { createRuntimeCredentialProvider } from "@/features/security/supabase-auth";
import {
  ENERGY_METRICS,
  isEnergySample,
  selectLatestEnergySamples,
  type EnergyMetricId,
} from "@/features/energy/energy-telemetry";
import { createTelemetryAdapter } from "@/lib/telemetry/create-adapter";
import {
  createDashboardTelemetryStore,
  deriveDashboardTelemetry,
  mergeDashboardTelemetry,
  type DashboardTelemetryStatus,
  type DashboardTelemetryStore,
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
const MAX_STARTUP_LIVE_SAMPLES = 2_000;
const DEFAULT_SCOPE = "__default_organization__";
const ENERGY_NODE_ID = process.env.NEXT_PUBLIC_NEXOLAB_ENERGY_NODE_ID?.trim() || "edge-01";
const HISTORY_HOURS = { "1h": 1, "6h": 6, "24h": 24 } as const;
const TERMINAL_STARTUP_STATES = new Set<TelemetryConnectionState>([
  "offline",
  "unauthorized",
  "forbidden",
  "configuration_error",
]);

export type EnergyHistoryRange = keyof typeof HISTORY_HOURS;
export type EnergyHistoryStatus = "idle" | "loading" | "ready" | "error";
export interface EnergyHistoryWindow {
  from: string;
  to: string;
}

interface RuntimeConfigResult {
  config: TelemetryRuntimeConfig | null;
  error: Error | null;
}

export interface EnergyTelemetryModel {
  mode: "demo" | "live";
  status: DashboardTelemetryStatus;
  samples: TelemetrySample[];
  freshSamples: TelemetrySample[];
  lastCapturedAt: string | null;
  ageMs: number | null;
  selectedMetric: EnergyMetricId;
  setSelectedMetric: (metric: EnergyMetricId) => void;
  historyRange: EnergyHistoryRange;
  setHistoryRange: (range: EnergyHistoryRange) => void;
  historyWindow: EnergyHistoryWindow | null;
  historySamples: TelemetrySample[];
  historyStatus: EnergyHistoryStatus;
  historyError: Error | null;
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

export function useEnergyTelemetry({
  enabled = true,
  organizationId = null,
}: {
  enabled?: boolean;
  organizationId?: string | null;
} = {}): EnergyTelemetryModel {
  const selectedOrganizationId = organizationId?.trim() || null;
  const scopeKey = enabled ? `${selectedOrganizationId ?? DEFAULT_SCOPE}:${ENERGY_NODE_ID}` : null;
  const [runtime] = useState<RuntimeConfigResult>(loadRuntimeConfig);
  const [store, setStore] = useState<DashboardTelemetryStore>(createDashboardTelemetryStore);
  const [activeScopeKey, setActiveScopeKey] = useState<string | null>(scopeKey);
  const [connectionState, setConnectionState] = useState<TelemetryConnectionState>(() =>
    runtime.config?.mode === "live" ? "connecting" : "idle",
  );
  const [hasLoadedSnapshot, setHasLoadedSnapshot] = useState(false);
  const [error, setError] = useState<Error | null>(runtime.error);
  const [clock, setClock] = useState(() => Date.now());
  const [generation, setGeneration] = useState(0);
  const [selectedMetric, setSelectedMetric] = useState<EnergyMetricId>(ENERGY_METRICS[0].id);
  const [historyRange, setHistoryRange] = useState<EnergyHistoryRange>("24h");
  const [historyWindow, setHistoryWindow] = useState<EnergyHistoryWindow | null>(null);
  const [historySamples, setHistorySamples] = useState<TelemetrySample[]>([]);
  const [historyStatus, setHistoryStatus] = useState<EnergyHistoryStatus>(
    runtime.config?.mode === "live" ? "loading" : "idle",
  );
  const [historyError, setHistoryError] = useState<Error | null>(null);
  const [activeHistoryKey, setActiveHistoryKey] = useState<string | null>(null);
  const [historyGeneration, setHistoryGeneration] = useState(0);
  const historyKey = scopeKey === null ? null : `${scopeKey}:${selectedMetric}:${historyRange}`;
  const selectedMetricRef = useRef(selectedMetric);
  const historyRangeRef = useRef(historyRange);
  const historyKeyRef = useRef(historyKey);
  const activeHistoryKeyRef = useRef(activeHistoryKey);
  const historyWindowRef = useRef(historyWindow);
  const pendingHistoryBreakUnitIdsRef = useRef<Set<number>>(new Set());
  const pendingHistoryMetricRef = useRef(selectedMetric);

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
    selectedMetricRef.current = selectedMetric;
    historyRangeRef.current = historyRange;
    historyKeyRef.current = historyKey;
    activeHistoryKeyRef.current = activeHistoryKey;
    historyWindowRef.current = historyWindow;
  }, [activeHistoryKey, historyKey, historyRange, historyWindow, selectedMetric]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      const now = Date.now();
      setClock(now);

      const currentWindow = historyWindowRef.current;
      if (
        currentWindow === null ||
        historyKeyRef.current === null ||
        activeHistoryKeyRef.current !== historyKeyRef.current
      ) {
        return;
      }

      const currentTo = Date.parse(currentWindow.to);
      if (!Number.isFinite(currentTo) || now <= currentTo) return;

      const rangeMs = HISTORY_HOURS[historyRangeRef.current] * 60 * 60 * 1000;
      const nextWindow = {
        from: new Date(now - rangeMs).toISOString(),
        to: new Date(now).toISOString(),
      };
      historyWindowRef.current = nextWindow;
      setHistoryWindow(nextWindow);
      setHistorySamples((current) =>
        mergeEnergyHistoryTail(current, [], {
          nodeId: ENERGY_NODE_ID,
          metric: selectedMetricRef.current,
          from: new Date(nextWindow.from),
          to: new Date(nextWindow.to),
        }),
      );
    }, CLOCK_TICK_MS);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const config = runtime.config;
    if (!config || config.mode === "demo" || !enabled || scopeKey === null) return;

    const controller = new AbortController();
    const resolvedOrganizationId =
      selectedOrganizationId ?? process.env.NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID?.trim() ?? null;
    const adapter = securedAdapter(config, resolvedOrganizationId);
    let subscription: TelemetrySubscription | null = null;
    let disposed = false;
    let snapshotPending = true;
    let bufferedLiveSamples: TelemetrySample[] = [];
    let liveReadySettled = false;
    let resolveLiveReady: () => void = () => undefined;
    let rejectLiveReady: (error: Error) => void = () => undefined;
    const liveReady = new Promise<void>((resolve, reject) => {
      resolveLiveReady = () => {
        if (liveReadySettled) return;
        liveReadySettled = true;
        resolve();
      };
      rejectLiveReady = (nextError) => {
        if (liveReadySettled) return;
        liveReadySettled = true;
        reject(nextError);
      };
    });
    pendingHistoryBreakUnitIdsRef.current = new Set();
    pendingHistoryMetricRef.current = selectedMetricRef.current;

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
      const accepted = samples.filter(
        (sample) => sample.node_id === ENERGY_NODE_ID && isEnergySample(sample),
      );
      if (disposed || accepted.length === 0) return;
      const now = Date.now();
      setStore((current) => mergeDashboardTelemetry(current, accepted, { now }));

      const selectedHistoryMetric = selectedMetricRef.current;
      if (pendingHistoryMetricRef.current !== selectedHistoryMetric) {
        pendingHistoryMetricRef.current = selectedHistoryMetric;
        pendingHistoryBreakUnitIdsRef.current = new Set();
      }
      const selectedTail = selectEnergyHistoryTail(accepted, ENERGY_NODE_ID, selectedHistoryMetric, now);
      const reconciliation = reconcileEnergyLiveHistory(selectedTail, pendingHistoryBreakUnitIdsRef.current);
      pendingHistoryBreakUnitIdsRef.current = reconciliation.pendingUnitIds;
      const tail = reconciliation.samples;
      const currentWindow = historyWindowRef.current;
      if (
        tail.length > 0 &&
        currentWindow !== null &&
        activeHistoryKeyRef.current === historyKeyRef.current
      ) {
        const currentTo = Date.parse(currentWindow.to);
        const capturedTimes = tail.map((sample) => Date.parse(sample.captured_at)).filter(Number.isFinite);
        const latestCapturedAt = capturedTimes.length > 0 ? Math.max(...capturedTimes) : currentTo;
        const nextTo = Math.max(currentTo, latestCapturedAt);
        const rangeMs = HISTORY_HOURS[historyRangeRef.current] * 60 * 60 * 1000;
        const nextWindow = {
          from: new Date(nextTo - rangeMs).toISOString(),
          to: new Date(nextTo).toISOString(),
        };
        historyWindowRef.current = nextWindow;
        setHistoryWindow(nextWindow);
        setHistorySamples((current) =>
          mergeEnergyHistoryTail(current, tail, {
            nodeId: ENERGY_NODE_ID,
            metric: selectedHistoryMetric,
            from: new Date(nextWindow.from),
            to: new Date(nextWindow.to),
          }),
        );
      }

      setError(null);
      setClock(now);
    };

    subscription = adapter.subscribe(
      { node_id: ENERGY_NODE_ID },
      {
        onSample: (sample) => {
          if (snapshotPending) {
            bufferedLiveSamples.push(sample);
            if (bufferedLiveSamples.length > MAX_STARTUP_LIVE_SAMPLES) {
              bufferedLiveSamples = bufferedLiveSamples.slice(-MAX_STARTUP_LIVE_SAMPLES);
            }
            return;
          }
          commit([sample]);
        },
        onStateChange: (state) => {
          if (disposed) return;
          setConnectionState(state);
          if (state === "connected") {
            resolveLiveReady();
            setError(null);
          } else if (TERMINAL_STARTUP_STATES.has(state)) {
            rejectLiveReady(new Error(`Energy telemetry WebSocket entered terminal state: ${state}`));
          }
        },
        onError: (nextError) => {
          if (!disposed) setError(nextError);
        },
        onHeartbeat: () => setClock(Date.now()),
      },
    );

    void liveReady
      .then(() => {
        if (disposed || controller.signal.aborted) {
          throw new Error("Energy telemetry startup was cancelled");
        }
        return adapter.latest({ node_id: ENERGY_NODE_ID, limit: 1000 }, controller.signal);
      })
      .then((snapshot) => {
        if (disposed) return;
        const buffered = bufferedLiveSamples;
        bufferedLiveSamples = [];
        snapshotPending = false;
        commit([...snapshot.items, ...buffered]);
        setHasLoadedSnapshot(true);
      })
      .catch((nextError: unknown) => {
        if (controller.signal.aborted || disposed) return;
        const buffered = bufferedLiveSamples;
        bufferedLiveSamples = [];
        snapshotPending = false;
        commit(buffered);
        setHasLoadedSnapshot(true);
        setError(nextError instanceof Error ? nextError : new Error("Failed to load energy snapshot"));
      });

    return () => {
      disposed = true;
      controller.abort();
      rejectLiveReady(new Error("Energy telemetry startup was cancelled"));
      bufferedLiveSamples = [];
      subscription?.close();
    };
  }, [enabled, generation, runtime.config, scopeKey, selectedOrganizationId]);

  useEffect(() => {
    const config = runtime.config;
    if (!config || config.mode === "demo" || !enabled || historyKey === null) return;

    const controller = new AbortController();
    const resolvedOrganizationId =
      selectedOrganizationId ?? process.env.NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID?.trim() ?? null;
    const adapter = securedAdapter(config, resolvedOrganizationId);
    const to = new Date();
    const from = new Date(to.getTime() - HISTORY_HOURS[historyRange] * 60 * 60 * 1000);
    const requestedWindow = { from: from.toISOString(), to: to.toISOString() };
    let disposed = false;

    activeHistoryKeyRef.current = historyKey;
    historyWindowRef.current = requestedWindow;

    void Promise.resolve().then(() => {
      if (disposed) return;
      setActiveHistoryKey(historyKey);
      setHistoryWindow(requestedWindow);
      setHistorySamples([]);
      setHistoryStatus("loading");
      setHistoryError(null);
    });

    void loadCompleteEnergyHistory(
      adapter,
      {
        nodeId: ENERGY_NODE_ID,
        metric: selectedMetric,
        from,
        to,
      },
      controller.signal,
    )
      .then((samples) => {
        if (disposed) return;
        const currentWindow = historyWindowRef.current ?? requestedWindow;
        setHistorySamples((current) =>
          mergeEnergyHistoryTail(samples, current, {
            nodeId: ENERGY_NODE_ID,
            metric: selectedMetric,
            from: new Date(currentWindow.from),
            to: new Date(currentWindow.to),
          }),
        );
        setHistoryStatus("ready");
        setHistoryError(null);
      })
      .catch((nextError: unknown) => {
        if (controller.signal.aborted || disposed) return;
        setHistoryStatus("error");
        setHistoryError(nextError instanceof Error ? nextError : new Error("Failed to load energy history"));
      });

    return () => {
      disposed = true;
      controller.abort();
    };
  }, [
    enabled,
    historyGeneration,
    historyKey,
    historyRange,
    runtime.config,
    selectedMetric,
    selectedOrganizationId,
  ]);

  const view = useMemo(() => {
    if (runtime.config?.mode !== "live" || !enabled || scopeKey === null || activeScopeKey !== scopeKey) {
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

  if (!runtime.config) {
    return {
      mode: "live",
      status: "configuration_error",
      samples: [],
      freshSamples: [],
      lastCapturedAt: null,
      ageMs: null,
      selectedMetric,
      setSelectedMetric,
      historyRange,
      setHistoryRange,
      historyWindow: null,
      historySamples: [],
      historyStatus: "error",
      historyError: runtime.error,
      retryHistory,
      error: runtime.error,
      retry,
    };
  }

  if (runtime.config.mode === "demo") {
    return {
      mode: "demo",
      status: "demo",
      samples: [],
      freshSamples: [],
      lastCapturedAt: null,
      ageMs: null,
      selectedMetric,
      setSelectedMetric,
      historyRange,
      setHistoryRange,
      historyWindow: null,
      historySamples: [],
      historyStatus: "idle",
      historyError: null,
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
    samples: selectLatestEnergySamples(resolvedView.samples),
    freshSamples: selectLatestEnergySamples(resolvedView.freshSamples),
    lastCapturedAt: resolvedView.lastCapturedAt,
    ageMs: resolvedView.ageMs,
    selectedMetric,
    setSelectedMetric,
    historyRange,
    setHistoryRange,
    historyWindow: activeHistoryKey === historyKey ? historyWindow : null,
    historySamples: activeHistoryKey === historyKey ? historySamples : [],
    historyStatus: activeHistoryKey === historyKey ? historyStatus : "loading",
    historyError: activeHistoryKey === historyKey ? historyError : null,
    retryHistory,
    error,
    retry,
  };
}
