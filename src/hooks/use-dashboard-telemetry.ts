"use client";

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

function securedAdapter(config: TelemetryRuntimeConfig, organizationId: string | null): TelemetryAdapter {
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
        setHistoryError(
          nextError instanceof Error ? nextError : new Error("Failed to load telemetry history"),
        );
      });

    return () => {
      disposed = true;
      controller.abort();
    };
  }, [enabled, historyGeneration, historyKey, historyRange, runtime.config, selectedOrganizationId]);

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
