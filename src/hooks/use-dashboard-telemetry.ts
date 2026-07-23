"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { kpis as demoKpis } from "@/data/dashboard";
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
  TelemetryConnectionState,
  TelemetryRuntimeConfig,
  TelemetrySample,
  TelemetrySubscription,
} from "@/lib/telemetry/types";

const CLOCK_TICK_MS = 5_000;
const STALE_AFTER_MS = 30_000;

interface RuntimeConfigResult {
  config: TelemetryRuntimeConfig | null;
  error: Error | null;
}

export interface DashboardTelemetryModel {
  mode: "demo" | "live";
  status: DashboardTelemetryStatus;
  view: DashboardTelemetryView | null;
  kpis: readonly DashboardKpiValue[] | typeof demoKpis;
  temperatures: TelemetrySample[];
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

export function useDashboardTelemetry(): DashboardTelemetryModel {
  const [runtime] = useState<RuntimeConfigResult>(loadRuntimeConfig);
  const [store, setStore] = useState<DashboardTelemetryStore>(createDashboardTelemetryStore);
  const [connectionState, setConnectionState] = useState<TelemetryConnectionState>(() =>
    runtime.config?.mode === "live" ? "connecting" : "disconnected",
  );
  const [hasLoadedSnapshot, setHasLoadedSnapshot] = useState(false);
  const [error, setError] = useState<Error | null>(runtime.error);
  const [clock, setClock] = useState(() => Date.now());
  const [generation, setGeneration] = useState(0);

  const retry = useCallback(() => {
    if (runtime.config?.mode !== "live") {
      return;
    }

    setConnectionState("connecting");
    setHasLoadedSnapshot(false);
    setError(null);
    setStore(createDashboardTelemetryStore());
    setClock(Date.now());
    setGeneration((value) => value + 1);
  }, [runtime.config]);

  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), CLOCK_TICK_MS);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const config = runtime.config;
    if (!config || config.mode === "demo") {
      return;
    }

    const controller = new AbortController();
    const adapter = createTelemetryAdapter(config);
    let subscription: TelemetrySubscription | null = null;
    let disposed = false;

    const commit = (samples: readonly TelemetrySample[]) => {
      if (disposed) {
        return;
      }
      setStore((current) =>
        mergeDashboardTelemetry(current, samples, {
          now: Date.now(),
        }),
      );
      setClock(Date.now());
    };

    const connectLive = () => {
      subscription = adapter.subscribe(
        { node_id: "edge-01" },
        {
          onSample: (sample) => commit([sample]),
          onStateChange: setConnectionState,
          onError: (nextError) => {
            if (!disposed) {
              setError(nextError);
            }
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
        if (controller.signal.aborted || disposed) {
          return;
        }
        setHasLoadedSnapshot(true);
        setError(
          nextError instanceof Error
            ? nextError
            : new Error("Failed to load telemetry snapshot"),
        );
      })
      .finally(() => {
        if (!disposed) {
          connectLive();
        }
      });

    return () => {
      disposed = true;
      controller.abort();
      subscription?.close();
    };
  }, [generation, runtime.config]);

  const view = useMemo(() => {
    if (runtime.config?.mode !== "live") {
      return null;
    }

    return deriveDashboardTelemetry(store, {
      now: clock,
      staleAfterMs: STALE_AFTER_MS,
      hasLoadedSnapshot,
      connectionState,
      error,
    });
  }, [clock, connectionState, error, hasLoadedSnapshot, runtime.config, store]);

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
    error,
    retry,
  };
}
