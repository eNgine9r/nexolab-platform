"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

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
const DEFAULT_SCOPE = "__default_organization__";
const HISTORY_HOURS = { "1h": 1, "6h": 6, "24h": 24 } as const;

export type EnergyHistoryRange = keyof typeof HISTORY_HOURS;
export type EnergyHistoryStatus = "idle" | "loading" | "ready" | "error";

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
  const scopeKey = enabled ? (selectedOrganizationId ?? DEFAULT_SCOPE) : null;
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
  const [historySamples, setHistorySamples] = useState<TelemetrySample[]>([]);
  const [historyStatus, setHistoryStatus] = useState<EnergyHistoryStatus>(
    runtime.config?.mode === "live" ? "loading" : "idle",
  );
  const [historyError, setHistoryError] = useState<Error | null>(null);
  const [activeHistoryKey, setActiveHistoryKey] = useState<string | null>(null);
  const [historyGeneration, setHistoryGeneration] = useState(0);
  const historyKey = scopeKey === null ? null : `${scopeKey}:${selectedMetric}:${historyRange}`;

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
    const resolvedOrganizationId =
      selectedOrganizationId ?? process.env.NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID?.trim() ?? null;
    const adapter = securedAdapter(config, resolvedOrganizationId);
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
      const accepted = samples.filter(isEnergySample);
      if (disposed || accepted.length === 0) return;
      setStore((current) => mergeDashboardTelemetry(current, accepted, { now: Date.now() }));
      setError(null);
      setClock(Date.now());
    };

    const connectLive = () => {
      subscription = adapter.subscribe(
        {},
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
      .latest({ limit: 1000 }, controller.signal)
      .then((snapshot) => {
        commit(snapshot.items);
        setHasLoadedSnapshot(true);
      })
      .catch((nextError: unknown) => {
        if (controller.signal.aborted || disposed) return;
        setHasLoadedSnapshot(true);
        setError(nextError instanceof Error ? nextError : new Error("Failed to load energy snapshot"));
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
    const resolvedOrganizationId =
      selectedOrganizationId ?? process.env.NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID?.trim() ?? null;
    const adapter = securedAdapter(config, resolvedOrganizationId);
    const to = new Date();
    const from = new Date(to.getTime() - HISTORY_HOURS[historyRange] * 60 * 60 * 1000);
    let disposed = false;

    void Promise.resolve().then(() => {
      if (disposed) return;
      setActiveHistoryKey(historyKey);
      setHistoryStatus("loading");
      setHistorySamples([]);
      setHistoryError(null);
    });

    void adapter
      .history(
        {
          metric: selectedMetric,
          from,
          to,
          limit: 1000,
        },
        controller.signal,
      )
      .then((response) => {
        if (disposed) return;
        setHistorySamples(response.items.filter(isEnergySample));
        setHistoryStatus("ready");
        setHistoryError(null);
      })
      .catch((nextError: unknown) => {
        if (controller.signal.aborted || disposed) return;
        setHistorySamples([]);
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
    historySamples: activeHistoryKey === historyKey ? historySamples : [],
    historyStatus: activeHistoryKey === historyKey ? historyStatus : "loading",
    historyError: activeHistoryKey === historyKey ? historyError : null,
    retryHistory,
    error,
    retry,
  };
}
