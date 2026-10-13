"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  readEnergyCadenceAuthority,
  type EnergyCadenceAuthority,
} from "@/features/energy/energy-cadence-authority";
import { selectEnergyHistoryTail } from "@/features/energy/energy-history";
import {
  invalidateEnergyComparisonHistory,
  loadEnergyComparisonHistory,
  mergeEnergyComparisonHistory,
  normalizeEnergyMetrics,
  readEnergyComparisonHistory,
  retainEnergyComparisonHistory,
  type EnergyComparisonHistory,
} from "@/features/energy/energy-comparison-history";
import {
  ENERGY_HISTORY_RECONCILIATION_OVERLAP_MS,
  energyHistoryRetentionKey,
  invalidateIncompatibleRetainedEnergyHistory,
  invalidateRetainedEnergyHistoryScope,
  readRetainedEnergyHistory,
  type EnergyHistoryRetentionKey,
} from "@/features/energy/energy-history-retention";
import {
  reconcileEnergyLiveHistory,
  seedEnergyLiveHistoryState,
  type EnergyLiveHistorySeed,
} from "@/features/energy/energy-live-history";
import { createAuthenticatedFetch } from "@/features/security/security-session";
import { createRuntimeCredentialProvider } from "@/features/security/supabase-auth";
import {
  ENERGY_METRICS,
  isEnergySample,
  resolveEnergyMeter,
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
const CADENCE_AUTHORITY_REFRESH_MS = 30_000;
const STALE_AFTER_MS = 30_000;
const MAX_STARTUP_LIVE_SAMPLES = 2_000;
const DEFAULT_SCOPE = "__default_organization__";
const DEFAULT_SECURITY_SCOPE = "__anonymous_identity__";
const ENERGY_NODE_ID = process.env.NEXT_PUBLIC_NEXOLAB_ENERGY_NODE_ID?.trim() || "edge-01";
const HISTORY_HOURS = { "1h": 1, "6h": 6, "12h": 12, "24h": 24, "7d": 7 * 24 } as const;
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

interface EnergyCadenceAuthorityState {
  scopeKey: string | null;
  ready: boolean;
  authority: EnergyCadenceAuthority | null;
}

export interface EnergyTelemetryModel {
  mode: "demo" | "live";
  status: DashboardTelemetryStatus;
  samples: TelemetrySample[];
  freshSamples: TelemetrySample[];
  lastCapturedAt: string | null;
  ageMs: number | null;
  cadenceAuthority: EnergyCadenceAuthority | null;
  selectedMetrics: readonly EnergyMetricId[];
  setSelectedMetrics: (metrics: readonly EnergyMetricId[]) => void;
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

function historyWindow(range: EnergyHistoryRange, to = new Date()): { from: Date; to: Date } {
  return {
    from: new Date(to.getTime() - HISTORY_HOURS[range] * 60 * 60 * 1000),
    to,
  };
}

function comparisonHistoryError(errors: EnergyComparisonHistory["errors"]): Error | null {
  const failed = ENERGY_METRICS.filter((metric) => errors[metric.id]);
  return failed.length === 0
    ? null
    : new Error(
        `Історія недоступна: ${failed.map((metric) => `${metric.label} (${errors[metric.id]})`).join("; ")}`,
      );
}

export function useEnergyTelemetry({
  enabled = true,
  organizationId = null,
  securityScopeId = null,
}: {
  enabled?: boolean;
  organizationId?: string | null;
  securityScopeId?: string | null;
} = {}): EnergyTelemetryModel {
  const selectedOrganizationId = organizationId?.trim() || null;
  const selectedSecurityScopeId = securityScopeId?.trim() || DEFAULT_SECURITY_SCOPE;
  const securityScopeKey = `${selectedSecurityScopeId}:${selectedOrganizationId ?? DEFAULT_SCOPE}`;
  const scopeKey = enabled ? `${securityScopeKey}:${ENERGY_NODE_ID}` : null;
  const [runtime] = useState<RuntimeConfigResult>(loadRuntimeConfig);
  const [store, setStore] = useState<DashboardTelemetryStore>(createDashboardTelemetryStore);
  const [activeScopeKey, setActiveScopeKey] = useState<string | null>(scopeKey);
  const [liveCoverageScopeKey, setLiveCoverageScopeKey] = useState<string | null>(null);
  const [connectionState, setConnectionState] = useState<TelemetryConnectionState>(() =>
    runtime.config?.mode === "live" ? "connecting" : "idle",
  );
  const [hasLoadedSnapshot, setHasLoadedSnapshot] = useState(false);
  const [error, setError] = useState<Error | null>(runtime.error);
  const [clock, setClock] = useState(() => Date.now());
  const [generation, setGeneration] = useState(0);
  const [selectedMetrics, updateSelectedMetrics] = useState<EnergyMetricId[]>([ENERGY_METRICS[0].id]);
  const selectedMetric = selectedMetrics[0] ?? ENERGY_METRICS[0].id;
  const setSelectedMetrics = useCallback((metrics: readonly EnergyMetricId[]) => {
    const next = normalizeEnergyMetrics(metrics);
    updateSelectedMetrics((current) => (current.join("|") === next.join("|") ? current : next));
  }, []);
  const setSelectedMetric = useCallback(
    (metric: EnergyMetricId) => setSelectedMetrics([metric]),
    [setSelectedMetrics],
  );
  const [historyRange, setHistoryRange] = useState<EnergyHistoryRange>("24h");
  const [historyWindowState, setHistoryWindow] = useState<EnergyHistoryWindow | null>(null);
  const [historySamples, setHistorySamples] = useState<TelemetrySample[]>([]);
  const [historyStatus, setHistoryStatus] = useState<EnergyHistoryStatus>(
    runtime.config?.mode === "live" ? "loading" : "idle",
  );
  const [historyError, setHistoryError] = useState<Error | null>(null);
  const [activeHistoryKey, setActiveHistoryKey] = useState<string | null>(null);
  const [historyGeneration, setHistoryGeneration] = useState(0);
  const [cadenceAuthorityState, setCadenceAuthorityState] = useState<EnergyCadenceAuthorityState>({
    scopeKey: null,
    ready: runtime.config?.mode !== "live",
    authority: null,
  });
  const historyRetention = useMemo<EnergyHistoryRetentionKey | null>(
    () =>
      scopeKey === null || selectedMetrics.length === 0
        ? null
        : {
            securityScope: securityScopeKey,
            nodeId: ENERGY_NODE_ID,
            metric: selectedMetrics.join("|"),
            range: historyRange,
          },
    [historyRange, scopeKey, securityScopeKey, selectedMetrics],
  );
  const historyKey = historyRetention === null ? null : energyHistoryRetentionKey(historyRetention);
  const storeRef = useRef(store);
  const historySamplesRef = useRef(historySamples);
  const selectedMetricsRef = useRef(selectedMetrics);
  const historyRangeRef = useRef(historyRange);
  const historyKeyRef = useRef(historyKey);
  const historyRetentionRef = useRef(historyRetention);
  const activeHistoryKeyRef = useRef(activeHistoryKey);
  const historyWindowRef = useRef(historyWindowState);
  const liveHistoryStateByMetricRef = useRef<Map<EnergyMetricId, EnergyLiveHistorySeed>>(new Map());
  const pendingHistoryMetricsRef = useRef(selectedMetrics.join("|"));
  const cadenceAuthorityRef = useRef<{ scopeKey: string | null; authority: EnergyCadenceAuthority | null }>({
    scopeKey: null,
    authority: null,
  });

  const retainActiveHistory = useCallback(
    (window: EnergyHistoryWindow, samples: readonly TelemetrySample[], loadedThrough?: string) => {
      const retentionKey = historyRetentionRef.current;
      if (retentionKey === null) return;
      const authorityScopeKey = `${retentionKey.securityScope}:${retentionKey.nodeId}`;
      const cadenceAuthorityFingerprint =
        cadenceAuthorityRef.current.scopeKey === authorityScopeKey
          ? (cadenceAuthorityRef.current.authority?.fingerprint ?? null)
          : null;
      for (const metric of selectedMetricsRef.current) {
        const key = { ...retentionKey, metric };
        const existing = loadedThrough === undefined ? readRetainedEnergyHistory(key) : null;
        if (existing && existing.cadenceAuthorityFingerprint !== cadenceAuthorityFingerprint) continue;
        const coverage = loadedThrough ?? existing?.loadedThrough;
        if (!coverage) continue;
        retainEnergyComparisonHistory(key, [metric], {
          window,
          loadedThrough: coverage,
          cadenceAuthorityFingerprint,
          samples: [...samples],
        });
      }
    },
    [],
  );

  const retry = useCallback(() => {
    if (runtime.config?.mode !== "live") return;
    const emptyStore = createDashboardTelemetryStore();
    storeRef.current = emptyStore;
    setConnectionState("connecting");
    setLiveCoverageScopeKey(null);
    setHasLoadedSnapshot(false);
    setError(null);
    setStore(emptyStore);
    setActiveScopeKey(scopeKey);
    setHistoryStatus("loading");
    setHistoryError(null);
    setClock(Date.now());
    setGeneration((value) => value + 1);
  }, [runtime.config, scopeKey]);

  const retryHistory = useCallback(() => {
    if (runtime.config?.mode !== "live") return;
    if (historyRetention !== null) invalidateEnergyComparisonHistory(historyRetention, selectedMetrics);
    if (scopeKey !== null && liveCoverageScopeKey !== scopeKey) {
      retry();
      return;
    }
    setHistoryGeneration((value) => value + 1);
  }, [historyRetention, liveCoverageScopeKey, retry, runtime.config, scopeKey, selectedMetrics]);

  useEffect(() => {
    if (!enabled) return;
    invalidateIncompatibleRetainedEnergyHistory(securityScopeKey);
  }, [enabled, securityScopeKey]);

  useEffect(() => {
    const config = runtime.config;
    if (!config || config.mode === "demo" || !enabled || scopeKey === null) {
      cadenceAuthorityRef.current = { scopeKey: null, authority: null };
      void Promise.resolve().then(() => {
        setCadenceAuthorityState({ scopeKey, ready: true, authority: null });
      });
      return;
    }

    const controller = new AbortController();
    const resolvedOrganizationId =
      selectedOrganizationId ?? process.env.NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID?.trim() ?? null;
    const authenticatedFetch = createAuthenticatedFetch(
      fetch.bind(globalThis),
      createRuntimeCredentialProvider(resolvedOrganizationId),
    );
    let disposed = false;
    let initialRead = true;

    cadenceAuthorityRef.current = { scopeKey, authority: null };
    void Promise.resolve().then(() => {
      if (!disposed) setCadenceAuthorityState({ scopeKey, ready: false, authority: null });
    });

    const refresh = async () => {
      let nextAuthority: EnergyCadenceAuthority | null;
      try {
        nextAuthority = await readEnergyCadenceAuthority(authenticatedFetch, controller.signal);
      } catch {
        if (controller.signal.aborted || disposed) return;
        nextAuthority = null;
      }
      if (controller.signal.aborted || disposed) return;

      const previous =
        cadenceAuthorityRef.current.scopeKey === scopeKey ? cadenceAuthorityRef.current.authority : null;
      if (nextAuthority !== null && previous !== null) {
        if (nextAuthority.revision < previous.revision) return;
        if (
          nextAuthority.revision === previous.revision &&
          nextAuthority.fingerprint !== previous.fingerprint
        ) {
          return;
        }
      }
      const changed = nextAuthority !== null && previous?.fingerprint !== nextAuthority.fingerprint;

      if (nextAuthority !== null) {
        cadenceAuthorityRef.current = { scopeKey, authority: nextAuthority };
        if (initialRead || changed) {
          setCadenceAuthorityState({ scopeKey, ready: true, authority: nextAuthority });
        }
      } else if (initialRead) {
        cadenceAuthorityRef.current = { scopeKey, authority: null };
        setCadenceAuthorityState({ scopeKey, ready: true, authority: null });
      }

      if (!initialRead && changed) {
        invalidateRetainedEnergyHistoryScope(securityScopeKey, ENERGY_NODE_ID);
        setHistoryGeneration((value) => value + 1);
      }
      initialRead = false;
    };

    void refresh();
    const refreshOnFocus = () => void refresh();
    window.addEventListener("focus", refreshOnFocus);
    const timer = window.setInterval(() => void refresh(), CADENCE_AUTHORITY_REFRESH_MS);
    return () => {
      disposed = true;
      controller.abort();
      window.removeEventListener("focus", refreshOnFocus);
      window.clearInterval(timer);
    };
  }, [enabled, runtime.config, scopeKey, securityScopeKey, selectedOrganizationId]);

  useEffect(() => {
    storeRef.current = store;
    historySamplesRef.current = historySamples;
    selectedMetricsRef.current = selectedMetrics;
    historyRangeRef.current = historyRange;
    historyKeyRef.current = historyKey;
    historyRetentionRef.current = historyRetention;
    activeHistoryKeyRef.current = activeHistoryKey;
    historyWindowRef.current = historyWindowState;
  }, [
    activeHistoryKey,
    historyKey,
    historyRange,
    historyRetention,
    historySamples,
    historyWindowState,
    selectedMetrics,
    store,
  ]);

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
      setHistorySamples((current) => {
        const activeCadenceAuthority =
          cadenceAuthorityRef.current.scopeKey === scopeKey ? cadenceAuthorityRef.current.authority : null;
        const next = mergeEnergyComparisonHistory(
          current,
          [],
          {
            nodeId: ENERGY_NODE_ID,
            from: new Date(nextWindow.from),
            to: new Date(nextWindow.to),
          },
          selectedMetricsRef.current,
          activeCadenceAuthority,
        );
        historySamplesRef.current = next;
        retainActiveHistory(nextWindow, next);
        return next;
      });
    }, CLOCK_TICK_MS);
    return () => window.clearInterval(timer);
  }, [retainActiveHistory, scopeKey]);

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
    liveHistoryStateByMetricRef.current = new Map();
    pendingHistoryMetricsRef.current = selectedMetricsRef.current.join("|");

    void Promise.resolve().then(() => {
      if (disposed) return;
      const emptyStore = createDashboardTelemetryStore();
      storeRef.current = emptyStore;
      setActiveScopeKey(scopeKey);
      setLiveCoverageScopeKey(null);
      setConnectionState("connecting");
      setHasLoadedSnapshot(false);
      setError(null);
      setStore(emptyStore);
      setClock(Date.now());
    });

    const commit = (samples: readonly TelemetrySample[]) => {
      const accepted = samples.filter(
        (sample) => sample.node_id === ENERGY_NODE_ID && isEnergySample(sample),
      );
      if (disposed || accepted.length === 0) return;
      const now = Date.now();
      const nextStore = mergeDashboardTelemetry(storeRef.current, accepted, { now });
      storeRef.current = nextStore;
      setStore(nextStore);

      const metrics = selectedMetricsRef.current;
      const selectionKey = metrics.join("|");
      if (pendingHistoryMetricsRef.current !== selectionKey) {
        pendingHistoryMetricsRef.current = selectionKey;
        liveHistoryStateByMetricRef.current = new Map(
          metrics.map((metric) => {
            const retained = selectEnergyHistoryTail(
              [...Object.values(nextStore.samples), ...historySamplesRef.current],
              ENERGY_NODE_ID,
              metric,
              now,
            );
            return [metric, seedEnergyLiveHistoryState(retained)];
          }),
        );
      }
      const tail = metrics.flatMap((metric) => {
        const selectedTail = selectEnergyHistoryTail(accepted, ENERGY_NODE_ID, metric, now);
        const seed = liveHistoryStateByMetricRef.current.get(metric);
        const reconciliation = reconcileEnergyLiveHistory(
          selectedTail,
          seed?.pendingUnitIds,
          seed?.newestCapturedAtByUnitId,
        );
        liveHistoryStateByMetricRef.current.set(metric, reconciliation);
        return reconciliation.samples;
      });
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
        setHistorySamples((current) => {
          const activeCadenceAuthority =
            cadenceAuthorityRef.current.scopeKey === scopeKey ? cadenceAuthorityRef.current.authority : null;
          const next = mergeEnergyComparisonHistory(
            current,
            tail,
            {
              nodeId: ENERGY_NODE_ID,
              from: new Date(nextWindow.from),
              to: new Date(nextWindow.to),
            },
            metrics,
            activeCadenceAuthority,
          );
          historySamplesRef.current = next;
          retainActiveHistory(nextWindow, next);
          return next;
        });
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
            setLiveCoverageScopeKey(scopeKey);
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
  }, [enabled, generation, retainActiveHistory, runtime.config, scopeKey, selectedOrganizationId]);

  useEffect(() => {
    const config = runtime.config;
    if (
      !config ||
      config.mode === "demo" ||
      !enabled ||
      historyKey === null ||
      historyRetention === null ||
      scopeKey === null ||
      liveCoverageScopeKey !== scopeKey ||
      cadenceAuthorityState.scopeKey !== scopeKey ||
      !cadenceAuthorityState.ready
    )
      return;

    const controller = new AbortController();
    const resolvedOrganizationId =
      selectedOrganizationId ?? process.env.NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID?.trim() ?? null;
    const adapter = securedAdapter(config, resolvedOrganizationId);
    const cadenceAuthority = cadenceAuthorityState.authority;
    const requested = historyWindow(historyRange);
    const requestedWindow = { from: requested.from.toISOString(), to: requested.to.toISOString() };
    const cadenceAuthorityFingerprint = cadenceAuthority?.fingerprint ?? null;
    // Only this authenticated scope's metric caches may seed a changed selection.
    const seededSamples = selectedMetrics.flatMap((metric) => {
      const key = { ...historyRetention, metric };
      const entry = readRetainedEnergyHistory(key);
      if (entry && entry.cadenceAuthorityFingerprint !== cadenceAuthorityFingerprint) {
        invalidateEnergyComparisonHistory(key, [metric]);
        return [];
      }
      return entry?.samples ?? [];
    });
    const retained = readEnergyComparisonHistory(historyRetention, selectedMetrics);
    const seed = mergeEnergyComparisonHistory(
      seededSamples,
      [],
      {
        nodeId: ENERGY_NODE_ID,
        from: requested.from,
        to: requested.to,
      },
      selectedMetrics,
      cadenceAuthority,
    );
    let disposed = false;
    activeHistoryKeyRef.current = historyKey;
    historyWindowRef.current = requestedWindow;
    historySamplesRef.current = seed;
    void Promise.resolve().then(() => {
      if (disposed) return;
      setActiveHistoryKey(historyKey);
      setHistoryWindow(requestedWindow);
      setHistorySamples(seed);
      setHistoryStatus(retained ? "ready" : "loading");
      setHistoryError(null);
    });
    const cleanup = () => {
      disposed = true;
      controller.abort();
    };
    const loadedThrough = retained ? Date.parse(retained.loadedThrough) : Number.NaN;
    if (Number.isFinite(loadedThrough) && loadedThrough >= requested.to.getTime()) {
      retainEnergyComparisonHistory(historyRetention, selectedMetrics, {
        window: requestedWindow,
        loadedThrough: retained!.loadedThrough,
        cadenceAuthorityFingerprint,
        samples: seed,
      });
      return cleanup;
    }
    const deltaFromMs = Number.isFinite(loadedThrough)
      ? Math.max(requested.from.getTime(), loadedThrough - ENERGY_HISTORY_RECONCILIATION_OVERLAP_MS)
      : requested.from.getTime();
    void loadEnergyComparisonHistory(
      adapter,
      {
        nodeId: ENERGY_NODE_ID,
        from: new Date(deltaFromMs),
        to: requested.to,
      },
      selectedMetrics,
      controller.signal,
      cadenceAuthority,
    )
      .then(({ samples, errors }) => {
        if (disposed) return;
        const currentWindow = historyWindowRef.current ?? requestedWindow;
        setHistorySamples((current) => {
          const next = mergeEnergyComparisonHistory(
            retained ? current : samples,
            retained ? samples : current,
            { nodeId: ENERGY_NODE_ID, from: new Date(currentWindow.from), to: new Date(currentWindow.to) },
            selectedMetrics,
            cadenceAuthority,
          );
          historySamplesRef.current = next;
          retainEnergyComparisonHistory(
            historyRetention,
            selectedMetrics,
            {
              window: currentWindow,
              loadedThrough: requestedWindow.to,
              cadenceAuthorityFingerprint,
              samples: next,
            },
            errors,
          );
          return next;
        });
        const failed = Object.keys(errors).length;
        setHistoryStatus(failed === selectedMetrics.length && seed.length === 0 ? "error" : "ready");
        setHistoryError(comparisonHistoryError(errors));
      })
      .catch((nextError: unknown) => {
        if (controller.signal.aborted || disposed) return;
        setHistoryStatus(retained ? "ready" : "error");
        setHistoryError(
          nextError instanceof Error ? nextError : new Error("Не вдалося завантажити історію."),
        );
      });
    return cleanup;
  }, [
    cadenceAuthorityState,
    enabled,
    historyGeneration,
    historyKey,
    historyRange,
    historyRetention,
    liveCoverageScopeKey,
    runtime.config,
    scopeKey,
    selectedMetrics,
    selectedOrganizationId,
  ]);

  useEffect(() => {
    const config = runtime.config;
    if (
      !config ||
      config.mode === "demo" ||
      !enabled ||
      historyKey === null ||
      scopeKey === null ||
      liveCoverageScopeKey === scopeKey ||
      !TERMINAL_STARTUP_STATES.has(connectionState)
    ) {
      return;
    }

    const nextError = new Error(
      `Energy history requires authenticated live coverage; WebSocket state is ${connectionState}`,
    );
    let disposed = false;
    void Promise.resolve().then(() => {
      if (disposed) return;
      activeHistoryKeyRef.current = historyKey;
      historyWindowRef.current = null;
      historySamplesRef.current = [];
      setActiveHistoryKey(historyKey);
      setHistoryWindow(null);
      setHistorySamples([]);
      setHistoryStatus("error");
      setHistoryError(nextError);
    });

    return () => {
      disposed = true;
    };
  }, [connectionState, enabled, historyKey, liveCoverageScopeKey, runtime.config, scopeKey]);

  const view = useMemo(() => {
    if (runtime.config?.mode !== "live" || !enabled || scopeKey === null || activeScopeKey !== scopeKey) {
      return null;
    }
    const baseView = deriveDashboardTelemetry(store, {
      now: clock,
      staleAfterMs: STALE_AFTER_MS,
      hasLoadedSnapshot,
      connectionState,
      error,
    });
    const authority = cadenceAuthorityState.scopeKey === scopeKey ? cadenceAuthorityState.authority : null;
    if (authority === null) return baseView;

    const freshSamples = baseView.samples.filter((sample) => {
      const meter = resolveEnergyMeter(sample);
      const capturedAt = Date.parse(sample.captured_at);
      if (meter === null || !Number.isFinite(capturedAt)) return false;
      const cadenceTolerance =
        authority.maximumSourceGapMs(meter.unitId, capturedAt, clock) ?? STALE_AFTER_MS;
      return clock - capturedAt <= cadenceTolerance;
    });

    let status = baseView.status;
    if (connectionState === "reconnecting") {
      status = freshSamples.length > 0 ? "reconnecting" : "stale";
    } else if (status === "live" || status === "stale") {
      status = freshSamples.length > 0 ? "live" : baseView.samples.length > 0 ? "stale" : "offline";
    }

    return { ...baseView, status, freshSamples };
  }, [
    activeScopeKey,
    cadenceAuthorityState,
    clock,
    connectionState,
    enabled,
    error,
    hasLoadedSnapshot,
    runtime.config,
    scopeKey,
    store,
  ]);

  const retainedHistoryForCurrentKey =
    historyRetention !== null && activeHistoryKey !== historyKey
      ? readEnergyComparisonHistory(historyRetention, selectedMetrics)
      : null;

  if (!runtime.config) {
    return {
      mode: "live",
      status: "configuration_error",
      samples: [],
      freshSamples: [],
      lastCapturedAt: null,
      ageMs: null,
      cadenceAuthority: null,
      selectedMetrics,
      setSelectedMetrics,
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
      cadenceAuthority: null,
      selectedMetrics,
      setSelectedMetrics,
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

  const currentHistoryWindow =
    selectedMetrics.length === 0
      ? null
      : activeHistoryKey === historyKey
        ? historyWindowState
        : (retainedHistoryForCurrentKey?.window ?? null);
  const currentHistorySamples =
    selectedMetrics.length === 0
      ? []
      : activeHistoryKey === historyKey
        ? historySamples
        : (retainedHistoryForCurrentKey?.samples ?? []);
  const currentHistoryStatus: EnergyHistoryStatus =
    selectedMetrics.length === 0
      ? "idle"
      : activeHistoryKey === historyKey
        ? historyStatus
        : retainedHistoryForCurrentKey
          ? "ready"
          : "loading";
  const currentHistoryError =
    selectedMetrics.length === 0 ? null : activeHistoryKey === historyKey ? historyError : null;

  return {
    mode: "live",
    status: resolvedView.status,
    samples: selectLatestEnergySamples(resolvedView.samples),
    freshSamples: selectLatestEnergySamples(resolvedView.freshSamples),
    lastCapturedAt: resolvedView.lastCapturedAt,
    ageMs: resolvedView.ageMs,
    cadenceAuthority: cadenceAuthorityState.scopeKey === scopeKey ? cadenceAuthorityState.authority : null,
    selectedMetrics,
    setSelectedMetrics,
    selectedMetric,
    setSelectedMetric,
    historyRange,
    setHistoryRange,
    historyWindow: currentHistoryWindow,
    historySamples: currentHistorySamples,
    historyStatus: currentHistoryStatus,
    historyError: currentHistoryError,
    retryHistory,
    error,
    retry,
  };
}
