"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { kpis as demoKpis } from "@/data/dashboard";
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
  loadCompleteTelemetryHistory,
  reconcileTelemetryHistoryEvents,
  seedTelemetryHistoryOrderingState,
  type TelemetryHistoryOrderingState,
  type TelemetryHistoryWindow,
} from "@/lib/telemetry/history";
import { getTelemetryRuntimeConfig } from "@/lib/telemetry/runtime-config";
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
const HISTORY_HOURS = { "1h": 1, "6h": 6, "24h": 24 } as const;
const HISTORY_PENDING_LIVE_LIMIT = 5_000;

interface RuntimeConfigResult {
  config: TelemetryRuntimeConfig | null;
  error: Error | null;
}

interface DashboardHistoryTailContext {
  scopeKey: string;
  historyKey: string;
  durationMs: number;
  window: TelemetryHistoryWindow;
}

export type DashboardHistoryRange = keyof typeof HISTORY_HOURS;
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
  const credentialProvider = createRuntimeCredentialProvider(organizationId);
  return createTelemetryAdapter(config, {
    rest: {
      fetch: createAuthenticatedFetch(fetch.bind(globalThis), credentialProvider),
    },
    websocket: { credentials: credentialProvider },
  });
}

function filterTemperatureScope(
  view: DashboardTelemetryView,
  allowedChannels: ReadonlySet<string> | null,
): DashboardTelemetryView {
  if (allowedChannels === null) return view;
  const visible = (sample: TelemetrySample) =>
    !isTemperatureProbeSample(sample) || allowedChannels.has(sample.channel_id);
  const samples = view.samples.filter(visible);
  const freshSamples = view.freshSamples.filter(visible);
  const lastCapturedAt = samples[0]?.captured_at ?? null;
  const ageMs = lastCapturedAt ? Math.max(0, Date.now() - Date.parse(lastCapturedAt)) : null;
  return { ...view, samples, freshSamples, lastCapturedAt, ageMs };
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
  return toMs === current.to.getTime()
    ? current
    : { from: new Date(toMs - durationMs), to: new Date(toMs) };
}

function samplesInsideHistoryWindow(
  samples: readonly TelemetrySample[],
  window: TelemetryHistoryWindow,
): TelemetrySample[] {
  const fromMs = window.from.getTime();
  const toMs = window.to.getTime();
  const byEventId = new Map<string, TelemetrySample>();
  for (const sample of samples) {
    const capturedAt = Date.parse(sample.captured_at);
    if (!Number.isFinite(capturedAt) || capturedAt < fromMs || capturedAt > toMs) continue;
    byEventId.set(sample.event_id, sample);
  }
  return [...byEventId.values()].sort(
    (left, right) =>
      Date.parse(left.captured_at) - Date.parse(right.captured_at) ||
      left.event_id.localeCompare(right.event_id),
  );
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
  const [activeScopeKey, setActiveScopeKey] = useState<string | null>(scopeKey);
  const [connectionState, setConnectionState] = useState<TelemetryConnectionState>(() =>
    runtime.config?.mode === "live" ? "connecting" : "idle",
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
  const historyOrderingRef = useRef<TelemetryHistoryOrderingState | null>(null);
  const historyPendingLiveRef = useRef<TelemetrySample[]>([]);
  const historyTailContextRef = useRef<DashboardHistoryTailContext | null>(null);
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

  const commitHistoryTail = useCallback((incoming: readonly TelemetrySample[], expectedScopeKey: string) => {
    const temperatureSamples = incoming.filter(isTemperatureProbeSample);
    if (temperatureSamples.length === 0) return;

    const context = historyTailContextRef.current;
    if (!context || context.scopeKey !== expectedScopeKey) return;

    const ordering = historyOrderingRef.current;
    if (ordering === null) {
      historyPendingLiveRef.current = [
        ...historyPendingLiveRef.current,
        ...temperatureSamples,
      ].slice(-HISTORY_PENDING_LIVE_LIMIT);
      return;
    }

    const reconciled = reconcileTelemetryHistoryEvents(temperatureSamples, ordering);
    historyOrderingRef.current = reconciled.state;
    if (reconciled.samples.length === 0) return;

    const nextWindow = advanceHistoryWindow(context.window, reconciled.samples);
    historyTailContextRef.current = { ...context, window: nextWindow };
    setHistorySamples((current) =>
      samplesInsideHistoryWindow([...current, ...reconciled.samples], nextWindow),
    );
    setHistoryWindow(serializedHistoryWindow(nextWindow));
  }, []);

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
      commitHistoryTail(samples, scopeKey);
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
    const adapter = securedAdapter(config, organizationId);
    const to = new Date();
    const from = new Date(to.getTime() - HISTORY_HOURS[historyRange] * 60 * 60 * 1000);
    const requestedWindow = { from, to };
    const durationMs = to.getTime() - from.getTime();
    let disposed = false;

    historyOrderingRef.current = null;
    historyPendingLiveRef.current = [];
    historyTailContextRef.current = {
      scopeKey,
      historyKey,
      durationMs,
      window: requestedWindow,
    };

    void Promise.resolve().then(() => {
      if (disposed) return;
      setActiveHistoryKey(historyKey);
      setHistoryStatus("loading");
      setHistoryError(null);
      setHistorySamples([]);
      setHistoryWindow(serializedHistoryWindow(requestedWindow));
    });

    void loadCompleteTelemetryHistory(
      adapter,
      { metric: "temperature.probe" },
      requestedWindow,
      { signal: controller.signal },
    )
      .then((result) => {
        const context = historyTailContextRef.current;
        if (disposed || !context || context.historyKey !== historyKey) return;

        const persisted = result.samples.filter(isTemperatureProbeSample);
        const ordering = seedTelemetryHistoryOrderingState(persisted);
        const pending = historyPendingLiveRef.current;
        const reconciled = reconcileTelemetryHistoryEvents(pending, ordering);
        const finalWindow = advanceHistoryWindow(requestedWindow, reconciled.samples);
        const combined = samplesInsideHistoryWindow(
          [...persisted, ...reconciled.samples],
          finalWindow,
        );

        historyPendingLiveRef.current = [];
        historyOrderingRef.current = reconciled.state;
        historyTailContextRef.current = { ...context, window: finalWindow };
        setHistorySamples(combined);
        setHistoryWindow(serializedHistoryWindow(finalWindow));
        setHistoryStatus("ready");
        setHistoryError(null);
      })
      .catch((nextError: unknown) => {
        if (controller.signal.aborted || disposed) return;
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
  }, [enabled, historyGeneration, historyKey, historyRange, runtime.config, scopeKey, selectedOrganizationId]);

  const view = useMemo(() => {
    if (runtime.config?.mode !== "live" || !enabled || scopeKey === null || activeScopeKey !== scopeKey) {
      return null;
    }
    return filterTemperatureScope(
      deriveDashboardTelemetry(store, {
        now: clock,
        staleAfterMs: STALE_AFTER_MS,
        hasLoadedSnapshot,
        connectionState,
        error,
      }),
      allowedTemperatureChannels,
    );
  }, [
    activeScopeKey,
    allowedTemperatureChannels,
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
