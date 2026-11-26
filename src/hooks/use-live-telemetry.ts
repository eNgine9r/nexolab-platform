"use client";

import { createReconnectBackfillObserver } from "@/lib/telemetry/reconnect-backfill";
import { isAggregateUnsupported } from "@/lib/telemetry/history-aggregate";
import {
  aggregateViewportDetail,
  columnsViewportDetail,
  fetchAggregatedSeries,
  loadAggregatedLiveHistory,
  wireToIntervalStatistics,
  type ViewportDetail,
} from "@/features/live/live-aggregate-history";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  LIVE_HISTORY_MAX_POINTS_PER_CHANNEL,
  LIVE_HISTORY_MIN_SOURCE_GAP_MS,
  advanceLiveHistoryWindow,
  loadCompleteLiveHistory,
  type LiveHistoryResult,
  seedCadenceFromHistoryLoad,
  mergeLiveHistoryTail,
  reconcileLiveHistoryEvents,
  seedLiveHistoryOrderingState,
  type LiveHistoryOrderingState,
  type LiveHistoryWindow,
} from "@/features/live/live-history";
import {
  EMPTY_CADENCE_OBSERVATIONS,
  isLiveSampleFresh,
  liveFreshnessFor,
  observedCadenceMs,
  recordCadenceObservation,
  type CadenceObservations,
} from "@/features/live/freshness";
import {
  LIVE_SELECTION_LIMIT,
  liveChannelKey,
  reconcileLiveSelection,
  selectLatestLiveSamples,
} from "@/features/live/live-telemetry";
import {
  resolveChartPointBudget,
  type ChartDensityMode,
  type ChartPointBudgetResolution,
} from "@/features/charts/density";
import type { IntervalStatistics } from "@/features/charts/interval-statistics";
import {
  liveIntervalStatistics,
  pruneLiveIntervalSamples,
  recordLiveIntervalSamples,
  type LiveIntervalColumns,
} from "@/features/live/live-interval-columns";
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
  /** Observed per-channel acquisition timestamps for cadence-aware freshness (#1522). */
  cadence: CadenceObservations;
}

export interface LiveTelemetryModel {
  mode: "demo" | "live";
  status: LiveTelemetryStatus;
  connectionState: TelemetryConnectionState;
  samples: TelemetrySample[];
  freshSamples: TelemetrySample[];
  lastCapturedAt: string | null;
  /** Resolved chart detail budget for the current selection (#1620). */
  densityResolution?: ChartPointBudgetResolution;
  /** Exact interval statistics from raw persisted samples (#1660); consumers recompute when historySamples changes. */
  intervalStatistics?: (channelKey: string, fromMs: number, toMs: number) => IntervalStatistics | null;
  /** Per-channel observed cadence; absent means the default threshold applies. */
  cadenceObservations?: CadenceObservations;
  /** Render clock (5 s tick) used for time-dependent freshness. */
  clock?: number;
  selectedKeys: string[];
  /** A complete authenticated inventory is available for selection persistence. */
  selectionReady?: boolean;
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
  /** #1813: "aggregate" when the backend served extremum-preserving history, else "raw". */
  historySource?: "aggregate" | "raw";
  /** #1813: detailed measurements for the visible window (null at full range). */
  viewportDetail?: ViewportDetail | null;
  /** #1813: request detail for the committed viewport; null returns to the full-range view. */
  setDetailViewport?: (domain: { fromMs: number; toMs: number } | null) => void;
}

/** #1813: in aggregate mode, sliding live-window statistics are refreshed at most this often. */
const SERVER_STATISTICS_REFRESH_MS = 30_000;

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
  return { samples: {}, seenEventIds: [], rejectedFutureSamples: 0, cadence: EMPTY_CADENCE_OBSERVATIONS };
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
  let cadence = current.cadence;
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
    cadence = recordCadenceObservation(cadence, key, timestamp);
    const currentSample = samples[key];
    if (!currentSample || capturedAt(currentSample) <= timestamp) samples[key] = sample;
  }

  while (seenEventIds.length > 20_000) seenEventIds.shift();
  return changed ? { samples, seenEventIds, rejectedFutureSamples, cadence } : current;
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
  const freshSamples = samples.filter((sample) =>
    isLiveSampleFresh(sample, now, liveFreshnessFor(sample, liveChannelKey(sample), store.cadence)),
  );
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
  densityMode = "auto",
}: {
  enabled?: boolean;
  organizationId?: string | null;
  initialSelectedKeys?: string[];
  initialRange?: LiveHistoryRange;
  /** User-selected chart detail (#1620); the per-channel budget also depends on the selection size. */
  densityMode?: ChartDensityMode;
} = {}): LiveTelemetryModel {
  const selectedOrganizationId = organizationId?.trim() || null;
  const scopeKey = enabled ? (selectedOrganizationId ?? DEFAULT_SCOPE) : null;
  const [runtime] = useState<RuntimeConfigResult>(loadRuntimeConfig);
  const [store, setStore] = useState<LatestStore>(emptyLatestStore);
  const [connectionState, setConnectionState] = useState<TelemetryConnectionState>(() =>
    runtime.config?.mode === "live" ? "connecting" : "idle",
  );
  const [hasLoadedSnapshot, setHasLoadedSnapshot] = useState(false);
  const [hasCompleteInventory, setHasCompleteInventory] = useState(false);
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
  const pointsPerChannelRef = useRef<number>(LIVE_HISTORY_MAX_POINTS_PER_CHANNEL);
  const densityResolution = useMemo(
    () => resolveChartPointBudget(densityMode, Math.max(1, selectedKeys.length)),
    [densityMode, selectedKeys.length],
  );
  const pointsPerChannel = densityResolution.perSeries;
  // Declared before the history effect so a density change is visible to its reload.
  useEffect(() => {
    pointsPerChannelRef.current = pointsPerChannel;
  }, [pointsPerChannel]);
  const intervalColumnsRef = useRef<LiveIntervalColumns>({});
  // #1813: aggregate-mode channels have no raw columns in the browser; their exact statistics
  // come from the server (same semantics), cached per range and refreshed at most every 30 s for
  // a sliding live window so viewing history never loads telemetry ingestion.
  const aggregatedChannelsRef = useRef<Set<string>>(new Set());
  const loadedIdentitiesRef = useRef<readonly TelemetrySample[]>([]);
  const historyAdapterRef = useRef<TelemetryAdapter | null>(null);
  const serverStatsRef = useRef<Map<string, IntervalStatistics>>(new Map());
  const latestServerStatsRef = useRef<Map<string, IntervalStatistics>>(new Map());
  const statsRequestRef = useRef<{ key: string; startedAt: number; inFlight: boolean } | null>(null);
  const [statsVersion, setStatsVersion] = useState(0);
  const [historySource, setHistorySource] = useState<"aggregate" | "raw">("raw");
  const requestServerStatistics = useCallback((fromMs: number, toMs: number) => {
    const adapter = historyAdapterRef.current;
    if (!adapter?.historyAggregate || aggregatedChannelsRef.current.size === 0) return;
    const rangeKey = `${fromMs}|${toMs}`;
    const previous = statsRequestRef.current;
    const now = Date.now();
    if (previous?.key === rangeKey) return;
    if (previous?.inFlight) return;
    const previousDuration = previous
      ? Number(previous.key.split("|")[1]) - Number(previous.key.split("|")[0])
      : NaN;
    if (
      previous &&
      previousDuration === toMs - fromMs &&
      now - previous.startedAt < SERVER_STATISTICS_REFRESH_MS
    )
      return;
    const request = { key: rangeKey, startedAt: now, inFlight: true };
    statsRequestRef.current = request;
    const identities = loadedIdentitiesRef.current.filter((identity) =>
      aggregatedChannelsRef.current.has(liveChannelKey(identity)),
    );
    void fetchAggregatedSeries(
      adapter,
      identities.map((identity) => ({
        node_id: identity.node_id,
        equipment_id: identity.equipment_id,
        channel_id: identity.channel_id,
        metric: identity.metric,
      })),
      { from: new Date(fromMs), to: new Date(toMs) },
      1,
      { statistics: true },
    )
      .then((response) => {
        for (const identity of identities) {
          const series = response.series.find(
            (item) =>
              item.node_id === identity.node_id &&
              item.equipment_id === identity.equipment_id &&
              item.channel_id === identity.channel_id &&
              item.metric === identity.metric,
          );
          if (!series?.statistics) continue;
          const statistics = wireToIntervalStatistics(series.statistics, fromMs, toMs);
          const key = liveChannelKey(identity);
          serverStatsRef.current.set(`${key}|${rangeKey}`, statistics);
          latestServerStatsRef.current.set(key, statistics);
        }
        setStatsVersion((value) => value + 1);
      })
      .catch(() => undefined)
      .finally(() => {
        request.inFlight = false;
      });
  }, []);
  const intervalStatistics = useCallback(
    (channelKey: string, fromMs: number, toMs: number) => {
      if (!aggregatedChannelsRef.current.has(channelKey)) {
        return liveIntervalStatistics(intervalColumnsRef.current, channelKey, fromMs, toMs);
      }
      const exact = serverStatsRef.current.get(`${channelKey}|${fromMs}|${toMs}`);
      if (exact) return exact;
      // Never from display points: request exact server statistics; meanwhile show the latest
      // exact result for a window of the same length (it carries its own exact range).
      setTimeout(() => requestServerStatistics(fromMs, toMs), 0);
      const recent = latestServerStatsRef.current.get(channelKey);
      return recent && recent.toMs - recent.fromMs === toMs - fromMs ? recent : null;
    },
    // statsVersion: consumers recompute when new exact server statistics arrive.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [requestServerStatistics, statsVersion],
  );
  const selectedKeysRef = useRef(selectedKeys);
  const historyWindowRef = useRef(historyWindow);
  const historySamplesRef = useRef(historySamples);
  const historyRangeRef = useRef(historyRange);
  const orderingStateRef = useRef<LiveHistoryOrderingState>(seedLiveHistoryOrderingState([]));
  // #1805: continuity tolerance per channel, derived once from RAW history. Channels without
  // history fall back to their observed live cadence; never to the spacing of reduced points.
  const sourceGapByChannelRef = useRef<Map<string, number>>(new Map());
  const sourceGapMsFor = useCallback((channelKey: string): number | undefined => {
    const fromHistory = sourceGapByChannelRef.current.get(channelKey);
    if (fromHistory !== undefined) return fromHistory;
    const cadenceMs = observedCadenceMs(storeRef.current.cadence[channelKey]);
    return cadenceMs === null ? undefined : Math.max(LIVE_HISTORY_MIN_SOURCE_GAP_MS, cadenceMs * 3);
  }, []);
  // #1813: detail for the committed viewport. Raw channels: from the browser's raw columns, no
  // request. Aggregated channels: one cancellable request; a newer viewport aborts the older one.
  const [viewportDetail, setViewportDetail] = useState<ViewportDetail | null>(null);
  const detailControllerRef = useRef<AbortController | null>(null);
  const setDetailViewport = useCallback(
    (domain: { fromMs: number; toMs: number } | null) => {
      detailControllerRef.current?.abort();
      detailControllerRef.current = null;
      if (!domain || !(domain.toMs > domain.fromMs)) {
        setViewportDetail(null);
        return;
      }
      const identities = loadedIdentitiesRef.current;
      const budget = pointsPerChannelRef.current;
      const aggregated = aggregatedChannelsRef.current;
      const rawDetail = columnsViewportDetail(
        identities.filter((identity) => !aggregated.has(liveChannelKey(identity))),
        intervalColumnsRef.current,
        domain,
        budget,
        sourceGapMsFor,
      );
      setViewportDetail(rawDetail.channels.size > 0 ? rawDetail : null);
      const adapter = historyAdapterRef.current;
      const aggregatedIdentities = identities.filter((identity) => aggregated.has(liveChannelKey(identity)));
      if (!adapter?.historyAggregate || aggregatedIdentities.length === 0) return;
      const controller = new AbortController();
      detailControllerRef.current = controller;
      void aggregateViewportDetail(
        adapter,
        aggregatedIdentities,
        domain,
        budget,
        sourceGapMsFor,
        controller.signal,
      )
        .then((detail) => {
          if (controller.signal.aborted) return;
          setViewportDetail((current) =>
            current && current.channels.size > 0
              ? {
                  fromMs: Math.min(current.fromMs, detail.fromMs),
                  toMs: Math.max(current.toMs, detail.toMs),
                  coveredToMs: Math.max(current.coveredToMs, detail.coveredToMs),
                  channels: new Set([...current.channels, ...detail.channels]),
                  samples: current.samples.concat(detail.samples),
                }
              : detail,
          );
        })
        // A failed or superseded detail request keeps the full-range points; nothing is invented.
        .catch(() => undefined);
    },
    [sourceGapMsFor],
  );

  const setSelectedKeys = useCallback((keys: string[]) => {
    setSelectedKeysState([...new Set(keys)].slice(0, LIVE_SELECTION_LIMIT));
  }, []);

  const retry = useCallback(() => {
    if (runtime.config?.mode !== "live") return;
    const nextStore = emptyLatestStore();
    storeRef.current = nextStore;
    setStore(nextStore);
    setConnectionState("connecting");
    setHasLoadedSnapshot(false);
    setHasCompleteInventory(false);
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
        const next = mergeLiveHistoryTail(
          current,
          [],
          new Set(selectedKeysRef.current),
          nextWindow,
          pointsPerChannelRef.current,
          sourceGapMsFor,
        );
        historySamplesRef.current = next;
        return next;
      });
    }, CLOCK_TICK_MS);
    return () => window.clearInterval(timer);
  }, [sourceGapMsFor]);

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
      setHasCompleteInventory(false);
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
          const nextWindow = advanceLiveHistoryWindow(currentWindow, reconciliation.samples);
          if (nextWindow !== currentWindow) {
            historyWindowRef.current = nextWindow;
            setHistoryWindow(nextWindow);
          }
          recordLiveIntervalSamples(intervalColumnsRef.current, reconciliation.samples);
          pruneLiveIntervalSamples(intervalColumnsRef.current, nextWindow.from.getTime());
          setHistorySamples((current) => {
            const next = mergeLiveHistoryTail(
              current,
              reconciliation.samples,
              selected,
              nextWindow,
              pointsPerChannelRef.current,
              sourceGapMsFor,
            );
            historySamplesRef.current = next;
            return next;
          });
        }
      }

      setError(null);
      setClock(now);
    };

    const observeReconnect = createReconnectBackfillObserver(() => {
      if (!disposed) setHistoryGeneration((value) => value + 1);
    });
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
          observeReconnect(state);
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
        setHasCompleteInventory(true);
      })
      .catch((nextError: unknown) => {
        if (controller.signal.aborted || disposed) return;
        const buffered = bufferedLiveSamples;
        bufferedLiveSamples = [];
        snapshotPending = false;
        commit(buffered);
        setHasLoadedSnapshot(true);
        setHasCompleteInventory(false);
        setError(nextError instanceof Error ? nextError : new Error("Failed to load telemetry inventory"));
      });

    return () => {
      disposed = true;
      controller.abort();
      rejectLiveReady(new Error("Telemetry startup was cancelled"));
      bufferedLiveSamples = [];
      subscription?.close();
    };
  }, [enabled, generation, runtime.config, scopeKey, selectedOrganizationId, sourceGapMsFor]);

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
    if (!hasCompleteInventory) return;
    if (reconciledSelectedKeys.length === selectedKeys.length) return;
    void Promise.resolve().then(() => setSelectedKeysState(reconciledSelectedKeys));
  }, [hasCompleteInventory, reconciledSelectedKeys, selectedKeys.length]);

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
    const selected = new Set(selectedKey ? selectedKey.split("\u001f") : []);
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

    historyAdapterRef.current = adapter;
    loadedIdentitiesRef.current = historyIdentities;
    detailControllerRef.current?.abort();
    const loadRaw = () =>
      loadCompleteLiveHistory(
        adapter,
        historyIdentities,
        requestedWindow,
        controller.signal,
        pointsPerChannelRef.current,
      );
    // #1813: extremum-preserving aggregated history when the backend serves it; otherwise (404 on
    // backends without #1811, remembered for this page) the raw path, unchanged.
    const load: Promise<LiveHistoryResult & { aggregatedChannels?: Set<string> }> = adapter.historyAggregate
      ? loadAggregatedLiveHistory(
          adapter,
          historyIdentities,
          requestedWindow,
          controller.signal,
          pointsPerChannelRef.current,
          sourceGapMsFor,
        ).catch((nextError: unknown) => {
          if (isAggregateUnsupported(nextError)) return loadRaw();
          throw nextError;
        })
      : loadRaw();
    void load
      .then((result) => {
        if (disposed) return;
        aggregatedChannelsRef.current = result.aggregatedChannels ?? new Set();
        serverStatsRef.current = new Map();
        latestServerStatsRef.current = new Map();
        statsRequestRef.current = null;
        setHistorySource(aggregatedChannelsRef.current.size > 0 ? "aggregate" : "raw");
        setViewportDetail(null);
        // #1522: seed per-channel cadence from the persisted history that was
        // already requested for the selected channels; no additional requests.
        // Use the raw tail, never the chart-reduced series (bucket spacing would
        // inflate the threshold and show stale data as Live).
        const seeded = seedCadenceFromHistoryLoad(storeRef.current.cadence, result);
        if (seeded !== storeRef.current.cadence) {
          const nextStore = { ...storeRef.current, cadence: seeded };
          storeRef.current = nextStore;
          setStore(nextStore);
        }
        sourceGapByChannelRef.current = result.sourceGapMsByChannel;
        setHistorySamples((current) => {
          const next = mergeLiveHistoryTail(
            result.samples,
            current,
            selected,
            requestedWindow,
            pointsPerChannelRef.current,
            sourceGapMsFor,
          );
          historySamplesRef.current = next;
          // Raw columns from the load, plus live samples that arrived while it was loading.
          intervalColumnsRef.current = result.intervalColumns;
          recordLiveIntervalSamples(intervalColumnsRef.current, current);
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
    pointsPerChannel,
    runtime.config,
    scopeKey,
    selectedKey,
    selectedOrganizationId,
    sourceGapMsFor,
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
      selectionReady: false,
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
      selectionReady: false,
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
    cadenceObservations: store.cadence,
    intervalStatistics,
    densityResolution,
    clock,
    selectedKeys: hasCompleteInventory ? reconciledSelectedKeys : selectedKeys,
    selectionReady: enabled && hasCompleteInventory && liveCoverageScopeKey === scopeKey,
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
    historySource,
    viewportDetail,
    setDetailViewport,
  };
}
