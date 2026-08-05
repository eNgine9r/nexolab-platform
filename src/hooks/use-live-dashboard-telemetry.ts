"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { dashboardItemIdentity, timeWindowMilliseconds } from "@/features/live-dashboards/model";
import type {
  LiveDashboard,
  LiveDashboardSeries,
  LiveDashboardTelemetryStatus,
} from "@/features/live-dashboards/types";
import { createRuntimeCredentialProvider } from "@/features/security/auth-runtime";
import { createAuthenticatedFetch } from "@/features/security/security-session";
import { createTelemetryAdapter } from "@/lib/telemetry/create-adapter";
import { getTelemetryRuntimeConfig } from "@/lib/telemetry/runtime-config";
import type {
  TelemetryAdapter,
  TelemetryConnectionState,
  TelemetryRuntimeConfig,
  TelemetrySample,
  TelemetrySubscription,
} from "@/lib/telemetry/types";

const STALE_AFTER_MS = 30_000;
const MAX_HISTORY_SAMPLES = 8_000;
const MAX_HISTORY_SAMPLES_PER_SERIES = 500;

interface RuntimeResult {
  config: TelemetryRuntimeConfig | null;
  error: Error | null;
}

export interface LiveDashboardTelemetryModel {
  status: LiveDashboardTelemetryStatus;
  connectionState: TelemetryConnectionState;
  series: LiveDashboardSeries[];
  lastCapturedAt: string | null;
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

function mergeHistory(
  current: readonly TelemetrySample[],
  incoming: readonly TelemetrySample[],
  from: number,
  limit: number,
): TelemetrySample[] {
  const events = new Map<string, TelemetrySample>();
  for (const sample of [...current, ...incoming]) {
    const captured = sampleTimestamp(sample);
    if (captured < from) continue;
    events.set(sample.event_id, sample);
  }
  return [...events.values()]
    .sort((left, right) => sampleTimestamp(left) - sampleTimestamp(right))
    .slice(-limit);
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
  const [runtime] = useState<RuntimeResult>(runtimeResult);
  const [latest, setLatest] = useState<Record<string, TelemetrySample>>({});
  const [history, setHistory] = useState<Record<string, TelemetrySample[]>>({});
  const [connectionState, setConnectionState] = useState<TelemetryConnectionState>("idle");
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<Error | null>(runtime.error);
  const [clock, setClock] = useState(Date.now);
  const [generation, setGeneration] = useState(0);
  const latestRef = useRef<Record<string, TelemetrySample>>({});
  const historyRef = useRef<Record<string, TelemetrySample[]>>({});
  const renderTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const retry = useCallback(() => {
    setError(null);
    setLoaded(false);
    setConnectionState("connecting");
    setGeneration((value) => value + 1);
  }, []);

  useEffect(() => {
    const interval = globalThis.setInterval(() => setClock(Date.now()), 5_000);
    return () => globalThis.clearInterval(interval);
  }, []);

  useEffect(() => {
    const config = runtime.config;
    if (!enabled || !dashboard || dashboard.status !== "active") {
      latestRef.current = {};
      historyRef.current = {};
      setLatest({});
      setHistory({});
      setLoaded(false);
      setConnectionState("idle");
      return;
    }
    if (!config || config.mode !== "live") {
      setError(runtime.error ?? new Error("Selected-series telemetry requires live mode."));
      setConnectionState("configuration_error");
      return;
    }

    const controller = new AbortController();
    const adapter = securedAdapter(config, organizationId);
    const subscriptions: TelemetrySubscription[] = [];
    const itemKeys = new Set(dashboard.items.map(dashboardItemIdentity));
    const windowMs = timeWindowMilliseconds(dashboard.time_window);
    const windowFrom = Date.now() - windowMs;
    const perSeriesLimit = Math.max(
      50,
      Math.min(
        MAX_HISTORY_SAMPLES_PER_SERIES,
        Math.floor(MAX_HISTORY_SAMPLES / Math.max(1, dashboard.items.length)),
      ),
    );
    let disposed = false;

    latestRef.current = {};
    historyRef.current = {};
    setLatest({});
    setHistory({});
    setLoaded(false);
    setError(null);
    setConnectionState("connecting");

    const flush = () => {
      if (disposed) return;
      setLatest({ ...latestRef.current });
      setHistory({ ...historyRef.current });
      setClock(Date.now());
      renderTimerRef.current = null;
    };

    const scheduleFlush = (immediate = false) => {
      if (disposed) return;
      if (immediate) {
        if (renderTimerRef.current !== null) globalThis.clearTimeout(renderTimerRef.current);
        renderTimerRef.current = null;
        flush();
        return;
      }
      if (renderTimerRef.current !== null) return;
      renderTimerRef.current = globalThis.setTimeout(flush, dashboard.refresh_seconds * 1_000);
    };

    const commitSample = (sample: TelemetrySample, immediate = false) => {
      const key = dashboardItemIdentity(sample);
      if (!itemKeys.has(key)) return;
      latestRef.current[key] = newestSample(latestRef.current[key], sample);
      historyRef.current[key] = mergeHistory(
        historyRef.current[key] ?? [],
        [sample],
        Date.now() - windowMs,
        perSeriesLimit,
      );
      scheduleFlush(immediate || Object.keys(latestRef.current).length === 1);
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

    const latestRequests = dashboard.items.map(async (item) => {
      const response = await adapter.latest(
        { channel_id: item.channel_id, metric: item.metric, limit: 1, offset: 0 },
        controller.signal,
      );
      return response.items;
    });
    const historyRequests = dashboard.items.map(async (item) => {
      const response = await adapter.history(
        {
          channel_id: item.channel_id,
          metric: item.metric,
          from: new Date(windowFrom),
          to: new Date(),
          limit: perSeriesLimit,
          offset: 0,
        },
        controller.signal,
      );
      return { key: dashboardItemIdentity(item), samples: response.items };
    });

    void Promise.all([Promise.all(latestRequests), Promise.all(historyRequests)])
      .then(([latestPages, historyPages]) => {
        if (disposed) return;
        for (const page of latestPages) for (const sample of page) commitSample(sample, true);
        for (const page of historyPages) {
          historyRef.current[page.key] = mergeHistory(
            historyRef.current[page.key] ?? [],
            page.samples,
            windowFrom,
            perSeriesLimit,
          );
          for (const sample of page.samples) {
            latestRef.current[page.key] = newestSample(latestRef.current[page.key], sample);
          }
        }
        setLoaded(true);
        scheduleFlush(true);
      })
      .catch((nextError: unknown) => {
        if (disposed || controller.signal.aborted) return;
        setLoaded(true);
        setError(nextError instanceof Error ? nextError : new Error("Selected telemetry failed to load."));
        scheduleFlush(true);
      });

    return () => {
      disposed = true;
      controller.abort();
      for (const subscription of subscriptions) subscription.close();
      if (renderTimerRef.current !== null) globalThis.clearTimeout(renderTimerRef.current);
      renderTimerRef.current = null;
    };
  }, [dashboard, enabled, generation, organizationId, runtime.config, runtime.error]);

  const series = useMemo<LiveDashboardSeries[]>(() => {
    if (!dashboard) return [];
    return dashboard.items.map((item) => {
      const key = dashboardItemIdentity(item);
      return { item, latest: latest[key] ?? null, history: history[key] ?? [] };
    });
  }, [dashboard, history, latest]);

  const samples = series.flatMap((item) => (item.latest ? [item.latest] : []));
  const lastCapturedAt =
    [...samples].sort((left, right) => sampleTimestamp(right) - sampleTimestamp(left))[0]?.captured_at ??
    null;

  return {
    status: deriveStatus(connectionState, loaded, samples, error, clock),
    connectionState,
    series,
    lastCapturedAt,
    error,
    retry,
  };
}
