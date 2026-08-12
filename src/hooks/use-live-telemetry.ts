"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  loadCompleteLiveHistory,
  mergeLiveHistoryTail,
  reconcileLiveHistoryEvents,
  seedLiveHistoryOrderingState,
  type LiveHistoryOrderingState,
  type LiveHistoryWindow,
} from "@/features/live/live-history";
import {
  liveChannelKey,
  reconcileLiveSelection,
  selectLatestLiveSamples,
} from "@/features/live/live-telemetry";
import { createAuthenticatedFetch } from "@/features/security/security-session";
import { createRuntimeCredentialProvider } from "@/features/security/supabase-auth";
import { createTelemetryAdapter } from "@/lib/telemetry/create-adapter";
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
const MAX_STARTUP_LIVE_SAMPLES = 4_000;
const MAX_LATEST_PAGES = 100;
const LATEST_PAGE_SIZE = 1_000;
const DEFAULT_SCOPE = "__default_organization__";
const TERMINAL_STARTUP_STATES = new Set<TelemetryConnectionState>([
  "offline",
  "unauthorized",
  "forbidden",
  "configuration_error",
]);
const RANGE_HOURS = { "1h": 1, "6h": 6, "24h": 24, "7d": 24 * 7 } as const;

export type LiveHistoryRange = keyof typeof RANGE_HOURS;
export type LiveHistoryStatus = "idle" | "loading" | "ready" | "error";
export type LiveTelemetryStatus =
  | "connecting"
  | "live"
  | "reconnecting"
  | "stale"
  | "offline"
  | "unauthorized"
  | "forbidden"
  | "configuration_error"
  | "error";

interface RuntimeConfigResult {
  config: TelemetryRuntimeConfig | null;
  error: Error | null;
}

interface LatestStore {
  samples: Record<string, TelemetrySample>;
  seenEventIds: string[];
  rejectedFutureSamples: number;
}

export interface LiveTelemetryModel {
  mode: "demo" | "live";
  status: LiveTelemetryStatus;
  connectionState: TelemetryConnectionState;
  samples: TelemetrySample[];
  freshSamples: TelemetrySample[];
  lastCapturedAt: string | null;
  selectedKeys: string[];
  setSelectedKeys: (keys: string[]) => void;
  historyRange: LiveHistoryRange;
  setHistoryRange: (range: LiveHistoryRange) => void;
  historyWindow: LiveHistoryWindow | null;
  historySamples: TelemetrySample[];
  historyStatus: LiveHistoryStatus;
  historySnapshotAt: string | null;
  historyError: Error | null;
  rejectedFutureSamples: number;
  error: Error | null;
  retry: () => void;
  retryHistory: () => void;
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
    rest: { fetch: createAuthenticatedFetch(fetch.bind(globalThis), credentialProvider) },
    websocket: { credentials: credentialProvider },
  });
}

function emptyLatestStore(): LatestStore {
  return { samples: {}, seenEventIds: [], rejectedFutureSamples: 0 };
}

function capturedAt(sample: TelemetrySample): number {
  return Date.parse(sample.captured_at);
}

function mergeLatestStore(
  current: LatestStore,
  incoming: readonly TelemetrySample[],
  now = Date.now(),
): LatestStore {
  const samples = { ...current.samples };
  const seen = new Set(current.seenEventIds);
  const seenEventIds = [...current.seenEventIds];
  let rejectedFutureSamples = current.rejectedFutureSamples;
  let changed = false;

  for (const sample of incoming) {
    if (seen.has(sample.event_id)) continue;
    const timestamp = capturedAt(sample);
    if (!Number.isFinite(timestamp) || timestamp > now + 30_000) {
      rejectedFutureSamples += 1;
      changed = true;
      continue;
    }

    seen.add(sample.event_id);
    seenEventIds.push(sample.event_id);
    changed = true;
    const key = liveChannelKey(sample);
    const currentSample = samples[key];
    if (!currentSample || capturedAt(currentSample) <= timestamp) samples[key] = sample;
  }

  while (seenEventIds.length > 20_000) seenEventIds.shift();
  return changed ? { samples, seenEventIds, rejectedFutureSamples } : current;
}

async function loadCompleteLatestInventory(
  adapter: TelemetryAdapter,
  signal?: AbortSignal,
): Promise<TelemetrySample[]> {
  const samples = new Map<string, TelemetrySample>();
  let offset = 0;

  for (let page = 0; page < MAX_LATEST_PAGES; page += 1) {
    const response = await adapter.latest({ limit: LATEST_PAGE_SIZE, offset }, signal);
    for (const sample of response.items) samples.set(sample.event_id, sample);
    if (response.next_offset === null) return selectLatestLiveSamples([...samples.values()]);
    if (response.next_offset <= offset) throw new Error("Telemetry latest pagination did not advance");
    offset = response.next_offset;
  }

  throw new Error("Telemetry latest inventory exceeded the supported pagination window");
}

function deriveStatus(
  store: LatestStore,
  connectionState: TelemetryConnectionState,
  hasLoadedSnapshot: boolean,
  error: Error | null,
  now: number,
): {
  status: LiveTelemetryStatus;
  samples: TelemetrySample[];
  freshSamples: TelemetrySample[];
  lastCapturedAt: string | null;
} {
  const samples = selectLatestLiveSamples(Object.values(store.samples));
  const freshSamples = samples.filter((sample) => now - capturedAt(sample) <= STALE_AFTER_MS);
  const lastCapturedAt =
    [...samples].sort((left, right) => capturedAt(right) - capturedAt(left))[0]?.captured_at ?? null;

  if (connectionState === "unauthorized") {
    return { status: "unauthorized", samples, freshSamples, lastCapturedAt };
  }
  if (connectionState === "forbidden") {
    return { status: "forbidden", samples, freshSamples, lastCapturedAt };
  }
  if (connectionState === "configuration_error") {
    return { status: "configuration_error", samples, freshSamples, lastCapturedAt };
  }
  if (error && samples.length === 0) return { status: "error", samples, freshSamples, lastCapturedAt };
  if (!hasLoadedSnapshot && samples.length === 0) {
    return { status: "connecting", samples, freshSamples, lastCapturedAt };
  }
  if (connectionState === "reconnecting") {
    return {
      status: freshSamples.length > 0 ? "reconnecting" : "stale",
      samples,
      freshSamples,
      lastCapturedAt,
    };
  }
  if (connectionState === "offline" || connectionState === "idle") {
    return { status: "offline", samples, freshSamples, lastCapturedAt };
  }
  if (freshSamples.length === 0) {
    return {
      status: samples.length > 0 ? "stale" : "offline",
      samples,
      freshSamples,
      lastCapturedAt,
    };
  }
  return { status: "live", samples, freshSamples, lastCapturedAt };
}

export function useLiveTelemetry({
  enabled = true,
  organizationId = null,
  initialSelectedKeys = [],
  initialRange = "1h",
}: {
  enabled?: boolean;
  organizationId?: string | null;
  initialSelectedKeys?: string[];
  initialRange?: LiveHistoryRange;
} = {}): LiveTelemetryModel {
  const selectedOrganizationId = organizationId?.trim() || null;
  const scopeKey = enabled ? (selectedOrganizationId ?? DEFAULT_SCOPE) : null;
  const [runtime] = useState<RuntimeConfigResult>(loadRuntimeConfig);
  const [store, setStore] = useState<LatestStore>(emptyLatestStore);
  const [connectionState, setConnectionState] = useState<TelemetryConnectionState>(() =>
    runtime.config?.mode === "live" ? "connecting" : "idle",
  );
  const [hasLoadedSnapshot, setHasLoadedSnapshot] = useState(false);
  const [liveCoverageScopeKey, setLiveCoverageScopeKey] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(runtime.error);
  const [clock, setClock] = useState(Date.now);
  const [generation, setGeneration] = useState(0);
  const [selectedKeys, setSelectedKeysState] = useState<string[]>(() => [...new Set(initialSelectedKeys)]);
  const [historyRange, setHistoryRange] = useState<LiveHistoryRange>(initialRange);
  const [historyWindow, setHistoryWindow] = useState<LiveHistoryWindow | null>(null);
  const [historySamples, setHistorySamples] = useState<TelemetrySample[]>([]);
  const [historyStatus, setHistoryStatus] = useState<LiveHistoryStatus>("idle");
  const [historySnapshotAt, setHistorySnapshotAt] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<Error | null>(null);
  const [historyGeneration, setHistoryGeneration] = useState(0);
  const storeRef = useRef(store);
  const selectedKeysRef = useRef(selectedKeys);
  const historyWindowRef = useRef(historyWindow);
  const historySamplesRef = useRef(historySamples);
  const historyRangeRef = useRef(historyRange);
  const orderingStateRef = useRef<LiveHistoryOrderingState>(seedLiveHistoryOrderingState([]));

  const setSelectedKeys = useCallback((keys: string[]) => {
    setSelectedKeysState([...new Set(keys)].slice(0, 8));
  }, []);

  const retry = useCallback(() => {
    if (runtime.config?.mode !== "live") return;
    const nextStore = emptyLatestStore();
    storeRef.current = nextStore;
    setStore(nextStore);
    setConnectionState("connecting");
    setHasLoadedSnapshot(false);
    setLiveCoverageScopeKey(null);
    setError(null);
    setHistoryStatus(selectedKeysRef.current.length > 0 ? "loading" : "idle");
    setHistoryError(null);
    setGeneration((value) => value + 1);
  }, [runtime.config]);

  const retryHistory = useCallback(() => {
    if (scopeKey !== null && liveCoverageScopeKey !== scopeKey) {
      retry();
      return;
    }
    setHistoryGeneration((value) => value + 1);
  }, [liveCoverageScopeKey, retry, scopeKey]);

  useEffect(() => {
    storeRef.current = store;
    selectedKeysRef.current = selectedKeys;
    historyWindowRef.current = historyWindow;
    historySamplesRef.current = historySamples;
    historyRangeRef.current = historyRange;
  }, [historyRange, historySamples, historyWindow, selectedKeys, store]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      const now = Date.now();
      setClock(now);
      const currentWindow = historyWindowRef.current;
      if (!currentWindow || selectedKeysRef.current.length === 0) return;
      if (now <= currentWindow.to.getTime()) return;

      const rangeMs = RANGE_HOURS[historyRangeRef.current] * 60 * 60 * 1_000;
      const nextWindow = { from: new Date(now - rangeMs), to: new Date(now) };
      historyWindowRef.current = nextWindow;
      setHistoryWindow(nextWindow);
      setHistorySamples((current) => {
        const next = mergeLiveHistoryTail(current, [], new Set(selectedKeysRef.current), nextWindow);
        historySamplesRef.current = next;
        return next;
      });
    }, CLOCK_TICK_MS);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const config = runtime.config;
    if (!config || config.mode === "demo" || !enabled || scopeKey === null) return;

    const controller = new AbortController();
    const adapter = securedAdapter(config, selectedOrganizationId);
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

    void Promise.resolve().then(() => {
      if (disposed) return;
      const nextStore = emptyLatestStore();
      storeRef.current = nextStore;
      setStore(nextStore);
      setConnectionState("connecting");
      setLiveCoverageScopeKey(null);
      setHasLoadedSnapshot(false);
      setError(null);
      setClock(Date.now());
    });

    const commit = (incoming: readonly TelemetrySample[]) => {
      if (disposed || incoming.length === 0) return;
      const now = Date.now();
      const nextStore = mergeLatestStore(storeRef.current, incoming, now);
      storeRef.current = nextStore;
      setStore(nextStore);

      const currentWindow = historyWindowRef.current;
      const selected = new Set(selectedKeysRef.current);
      if (currentWindow && selected.size > 0) {
        const selectedIncoming = incoming.filter((sample) => selected.has(liveChannelKey(sample)));
        const reconciliation = reconcileLiveHistoryEvents(selectedIncoming, orderingStateRef.current);
        orderingStateRef.current = reconciliation.state;
        if (reconciliation.samples.length > 0) {
          setHistorySamples((current) => {
            const next = mergeLiveHistoryTail(current, reconciliation.samples, selected, currentWindow);
            historySamplesRef.current = next;
            return next;
          });
        }
      }

      setError(null);
      setClock(now);
    };

    subscription = adapter.subscribe(
      {},
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
            rejectLiveReady(new Error(`Telemetry WebSocket entered terminal state: ${state}`));
          }
        },
        onError: (nextError) => {
          if (!disposed) setError(nextError);
        },
        onHeartbeat: () => setClock(Date.now()),
      },
    );

    void liveReady
      .then(() => loadCompleteLatestInventory(adapter, controller.signal))
      .then((snapshot) => {
        if (disposed) return;
        const buffered = bufferedLiveSamples;
        bufferedLiveSamples = [];
        snapshotPending = false;
        commit([...snapshot, ...buffered]);
        setHasLoadedSnapshot(true);
      })
      .catch((nextError: unknown) => {
        if (controller.signal.aborted || disposed) return;
        const buffered = bufferedLiveSamples;
        bufferedLiveSamples = [];
        snapshotPending = false;
        commit(buffered);
        setHasLoadedSnapshot(true);
        setError(nextError instanceof Error ? nextError : new Error("Failed to load telemetry inventory"));
      });

    return () => {
      disposed = true;
      controller.abort();
      rejectLiveReady(new Error("Telemetry startup was cancelled"));
      bufferedLiveSamples = [];
      subscription?.close();
    };
  }, [enabled, generation, runtime.config, scopeKey, selectedOrganizationId]);

  const view = useMemo(
    () => deriveStatus(store, connectionState, hasLoadedSnapshot, error, clock),
    [clock, connectionState, error, hasLoadedSnapshot, store],
  );
  const reconciledSelectedKeys = useMemo(
    () => reconcileLiveSelection(selectedKeys, view.samples),
    [selectedKeys, view.samples],
  );
  const selectedIdentities = useMemo(() => {
    const selected = new Set(reconciledSelectedKeys);
    return view.samples.filter((sample) => selected.has(liveChannelKey(sample)));
  }, [reconciledSelectedKeys, view.samples]);
  const selectedKey = reconciledSelectedKeys.join("\u001f");
  const selectedIdentitiesRef = useRef(selectedIdentities);

  useEffect(() => {
    selectedIdentitiesRef.current = selectedIdentities;
  }, [selectedIdentities]);

  useEffect(() => {
    if (!hasLoadedSnapshot) return;
    if (reconciledSelectedKeys.length === selectedKeys.length) return;
    void Promise.resolve().then(() => setSelectedKeysState(reconciledSelectedKeys));
  }, [hasLoadedSnapshot, reconciledSelectedKeys, selectedKeys.length]);

  useEffect(() => {
    const config = runtime.config;
    if (
      !config ||
      config.mode === "demo" ||
      !enabled ||
      scopeKey === null ||
      liveCoverageScopeKey !== scopeKey ||
      selectedIdentitiesRef.current.length === 0
    ) {
      return;
    }

    const historyIdentities = selectedIdentitiesRef.current;
    const controller = new AbortController();
    const adapter = securedAdapter(config, selectedOrganizationId);
    const to = new Date();
    const from = new Date(to.getTime() - RANGE_HOURS[historyRange] * 60 * 60 * 1_000);
    const requestedWindow = { from, to };
    const selected = new Set(reconciledSelectedKeys);
    let disposed = false;

    orderingStateRef.current = seedLiveHistoryOrderingState([
      ...historyIdentities,
      ...historySamplesRef.current,
    ]);
    historyWindowRef.current = requestedWindow;

    void Promise.resolve().then(() => {
      if (disposed) return;
      setHistoryWindow(requestedWindow);
      setHistorySamples([]);
      historySamplesRef.current = [];
      setHistoryStatus("loading");
      setHistorySnapshotAt(null);
      setHistoryError(null);
    });

    void loadCompleteLiveHistory(adapter, historyIdentities, requestedWindow, controller.signal)
      .then((result) => {
        if (disposed) return;
        setHistorySamples((current) => {
          const next = mergeLiveHistoryTail(result.samples, current, selected, requestedWindow);
          historySamplesRef.current = next;
          orderingStateRef.current = seedLiveHistoryOrderingState([...historyIdentities, ...next]);
          return next;
        });
        setHistorySnapshotAt(result.snapshotAt);
        setHistoryStatus("ready");
        setHistoryError(null);
      })
      .catch((nextError: unknown) => {
        if (controller.signal.aborted || disposed) return;
        setHistoryStatus("error");
        setHistoryError(
          nextError instanceof Error ? nextError : new Error("Failed to load telemetry history"),
        );
      });

    return () => {
      disposed = true;
      controller.abort();
    };
  }, [
    enabled,
    historyGeneration,
    historyRange,
    liveCoverageScopeKey,
    reconciledSelectedKeys,
    runtime.config,
    scopeKey,
    selectedKey,
    selectedOrganizationId,
  ]);

  useEffect(() => {
    if (
      !enabled ||
      scopeKey === null ||
      selectedKeys.length === 0 ||
      liveCoverageScopeKey === scopeKey ||
      !TERMINAL_STARTUP_STATES.has(connectionState)
    ) {
      return;
    }

    const nextError = new Error(
      `Telemetry history requires authenticated live coverage; WebSocket state is ${connectionState}`,
    );
    let disposed = false;
    void Promise.resolve().then(() => {
      if (disposed) return;
      setHistoryWindow(null);
      setHistorySamples([]);
      setHistoryStatus("error");
      setHistorySnapshotAt(null);
      setHistoryError(nextError);
    });
    return () => {
      disposed = true;
    };
  }, [connectionState, enabled, liveCoverageScopeKey, scopeKey, selectedKeys.length]);

  if (!runtime.config) {
    return {
      mode: "live",
      status: "configuration_error",
      connectionState: "configuration_error",
      samples: [],
      freshSamples: [],
      lastCapturedAt: null,
      selectedKeys,
      setSelectedKeys,
      historyRange,
      setHistoryRange,
      historyWindow: null,
      historySamples: [],
      historyStatus: "error",
      historySnapshotAt: null,
      historyError: runtime.error,
      rejectedFutureSamples: 0,
      error: runtime.error,
      retry,
      retryHistory,
    };
  }

  if (runtime.config.mode === "demo") {
    return {
      mode: "demo",
      status: "offline",
      connectionState: "idle",
      samples: [],
      freshSamples: [],
      lastCapturedAt: null,
      selectedKeys,
      setSelectedKeys,
      historyRange,
      setHistoryRange,
      historyWindow: null,
      historySamples: [],
      historyStatus: "idle",
      historySnapshotAt: null,
      historyError: null,
      rejectedFutureSamples: 0,
      error: null,
      retry,
      retryHistory,
    };
  }

  return {
    mode: "live",
    status: view.status,
    connectionState,
    samples: view.samples,
    freshSamples: view.freshSamples,
    lastCapturedAt: view.lastCapturedAt,
    selectedKeys: reconciledSelectedKeys,
    setSelectedKeys,
    historyRange,
    setHistoryRange,
    historyWindow,
    historySamples,
    historyStatus: selectedKeys.length === 0 ? "idle" : historyStatus,
    historySnapshotAt,
    historyError,
    rejectedFutureSamples: store.rejectedFutureSamples,
    error,
    retry,
    retryHistory,
  };
}
