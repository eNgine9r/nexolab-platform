import type { SecurityCredentialProvider } from "@/features/security/security-session";

import { TelemetryRequestCoordinator } from "./request-coordinator";
import type {
  TelemetryCollectionResponse,
  TelemetryConnectionState,
  TelemetryDiagnosticEvent,
  TelemetryFilters,
  TelemetryLiveHandlers,
  TelemetryPageQuery,
  TelemetrySample,
  TelemetrySubscription,
} from "./types";
import { TelemetryWebSocketClient, type TelemetryWebSocketClientOptions } from "./websocket-client";

export interface TelemetryLiveSource {
  subscribe: (filters: TelemetryFilters, handlers: TelemetryLiveHandlers) => TelemetrySubscription;
}

export interface RoutePersistentTelemetryClientOptions {
  transitionGraceMs?: number;
  cacheTtlMs?: number;
  onEvict?: () => void;
}

interface RouteSubscriber {
  filters: TelemetryFilters;
  handlers: TelemetryLiveHandlers;
}

const LATEST_FILTER_KEYS = ["node_id", "equipment_id", "channel_id", "metric", "quality", "alarm"] as const;
const MAX_LATEST_QUERY_CACHE = 128;
const MAX_LATEST_SAMPLES = 20_000;
const DEFAULT_TRANSITION_GRACE_MS = 5_000;
const DEFAULT_CACHE_TTL_MS = 15 * 60 * 1_000;

let applicationShellRetainCount = 0;
let nextCredentialProviderId = 1;
const credentialProviderIds = new WeakMap<SecurityCredentialProvider, number>();
const sharedClients = new Map<string, RoutePersistentTelemetryClient>();

function sampleIdentity(sample: TelemetrySample): string {
  return [sample.node_id, sample.equipment_id, sample.channel_id, sample.metric].join("\u0000");
}

function capturedAt(sample: TelemetrySample): number {
  const parsed = Date.parse(sample.captured_at);
  return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY;
}

function matchesFilters(sample: TelemetrySample, filters: TelemetryFilters): boolean {
  return LATEST_FILTER_KEYS.every((key) => filters[key] === undefined || sample[key] === filters[key]);
}

function queryKey(query: TelemetryPageQuery): string {
  return JSON.stringify({
    node_id: query.node_id ?? null,
    equipment_id: query.equipment_id ?? null,
    channel_id: query.channel_id ?? null,
    metric: query.metric ?? null,
    quality: query.quality ?? null,
    alarm: query.alarm ?? null,
    limit: query.limit ?? null,
    offset: query.offset ?? null,
  });
}

function cloneCollection(response: TelemetryCollectionResponse): TelemetryCollectionResponse {
  return { ...response, items: [...response.items] };
}

function providerId(provider: SecurityCredentialProvider | undefined): string {
  if (!provider) return "anonymous";
  const existing = credentialProviderIds.get(provider);
  if (existing !== undefined) return String(existing);
  const created = nextCredentialProviderId;
  nextCredentialProviderId += 1;
  credentialProviderIds.set(provider, created);
  return String(created);
}

function sharedClientKey(websocketUrl: string, options: TelemetryWebSocketClientOptions): string {
  return [
    websocketUrl,
    providerId(options.credentials),
    options.authenticationRequired === undefined ? "runtime-auth" : String(options.authenticationRequired),
  ].join("::");
}

function canShare(options: TelemetryWebSocketClientOptions): boolean {
  return (
    options.createSocket === undefined &&
    options.reconnectDelaysMs === undefined &&
    options.connectionTimeoutMs === undefined &&
    options.authenticationTimeoutMs === undefined &&
    options.heartbeatTimeoutMs === undefined &&
    options.maxSeenEventIds === undefined
  );
}

export class RoutePersistentTelemetryClient {
  private readonly subscribers = new Map<number, RouteSubscriber>();
  private readonly latestSamples = new Map<string, TelemetrySample>();
  private readonly latestQueries = new Map<
    string,
    { query: TelemetryPageQuery; response: TelemetryCollectionResponse }
  >();
  private readonly transitionGraceMs: number;
  private readonly cacheTtlMs: number;
  private readonly onEvict?: () => void;
  private readonly requests: TelemetryRequestCoordinator;
  private sourceSubscription: TelemetrySubscription | null = null;
  private transitionTimer: ReturnType<typeof setTimeout> | null = null;
  private evictionTimer: ReturnType<typeof setTimeout> | null = null;
  private shellRetained = false;
  private disposed = false;
  private nextSubscriberId = 1;
  private connectionState: TelemetryConnectionState = "idle";
  private lastError: Error | null = null;
  private lastHeartbeat: string | null = null;

  constructor(
    private readonly source: TelemetryLiveSource,
    options: RoutePersistentTelemetryClientOptions = {},
  ) {
    this.transitionGraceMs = options.transitionGraceMs ?? DEFAULT_TRANSITION_GRACE_MS;
    this.cacheTtlMs = options.cacheTtlMs ?? DEFAULT_CACHE_TTL_MS;
    this.onEvict = options.onEvict;
    this.requests = new TelemetryRequestCoordinator(() => this.handleRequestActivityChange());
  }

  setApplicationShellRetained(retained: boolean): void {
    if (this.disposed) return;
    this.shellRetained = retained;
    if (!retained) this.dispose();
  }

  runRequest<T>(
    key: string,
    signal: AbortSignal | undefined,
    factory: (signal: AbortSignal) => Promise<T>,
  ): Promise<T> {
    if (this.disposed) return Promise.reject(new Error("Telemetry runtime scope is disposed"));
    this.cancelLifecycleTimers();
    return this.requests.request(key, signal, factory);
  }

  readCachedLatest(query: TelemetryPageQuery = {}): TelemetryCollectionResponse | null {
    const cached = this.latestQueries.get(queryKey(query));
    return cached ? cloneCollection(cached.response) : null;
  }

  seedLatest(query: TelemetryPageQuery, response: TelemetryCollectionResponse): void {
    if (this.disposed) return;
    for (const sample of response.items) this.rememberSample(sample);
    const key = queryKey(query);
    if (!this.latestQueries.has(key) && this.latestQueries.size >= MAX_LATEST_QUERY_CACHE) {
      const oldestKey = this.latestQueries.keys().next().value as string | undefined;
      if (oldestKey !== undefined) this.latestQueries.delete(oldestKey);
    }
    this.latestQueries.set(key, { query: { ...query }, response: cloneCollection(response) });
  }

  subscribe(filters: TelemetryFilters, handlers: TelemetryLiveHandlers): TelemetrySubscription {
    if (this.disposed) throw new Error("Telemetry runtime scope is disposed");
    this.cancelLifecycleTimers();
    const subscriberId = this.nextSubscriberId;
    this.nextSubscriberId += 1;
    this.subscribers.set(subscriberId, { filters: { ...filters }, handlers });
    this.ensureStarted();

    queueMicrotask(() => {
      const subscriber = this.subscribers.get(subscriberId);
      if (!subscriber) return;
      if (this.connectionState !== "idle") {
        subscriber.handlers.onStateChange?.(this.connectionState);
      }
      if (this.lastError) subscriber.handlers.onError?.(this.lastError);
      if (this.lastHeartbeat) subscriber.handlers.onHeartbeat?.(this.lastHeartbeat);
      for (const sample of this.latestSamples.values()) {
        if (matchesFilters(sample, subscriber.filters)) subscriber.handlers.onSample(sample);
      }
    });

    let closed = false;
    return {
      close: () => {
        if (closed) return;
        closed = true;
        this.subscribers.delete(subscriberId);
        this.scheduleLifecycleIfIdle();
      },
    };
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.shellRetained = false;
    this.cancelLifecycleTimers();
    this.stopTransport();
    this.requests.abortAll();
    this.subscribers.clear();
    this.latestSamples.clear();
    this.latestQueries.clear();
    this.lastError = null;
    this.lastHeartbeat = null;
    this.onEvict?.();
  }

  private ensureStarted(): void {
    if (this.sourceSubscription || this.disposed || this.subscribers.size === 0) return;
    this.sourceSubscription = this.source.subscribe(
      {},
      {
        onSample: (sample) => this.handleSample(sample),
        onStateChange: (state) => this.handleStateChange(state),
        onError: (error) => this.handleError(error),
        onHeartbeat: (serverTime) => this.handleHeartbeat(serverTime),
        onDiagnostic: (event) => this.handleDiagnostic(event),
      },
    );
  }

  private stopTransport(): void {
    this.sourceSubscription?.close();
    this.sourceSubscription = null;
    this.connectionState = "idle";
  }

  private handleRequestActivityChange(): void {
    if (this.requests.hasConsumers) {
      this.cancelLifecycleTimers();
    } else {
      this.scheduleLifecycleIfIdle();
    }
  }

  private scheduleLifecycleIfIdle(): void {
    if (
      this.disposed ||
      !this.shellRetained ||
      this.subscribers.size > 0 ||
      this.requests.hasConsumers
    ) {
      return;
    }
    if (this.transitionTimer === null) {
      this.transitionTimer = setTimeout(() => {
        this.transitionTimer = null;
        if (this.subscribers.size === 0 && !this.requests.hasConsumers) this.stopTransport();
      }, this.transitionGraceMs);
    }
    if (this.evictionTimer === null) {
      this.evictionTimer = setTimeout(() => {
        this.evictionTimer = null;
        if (this.subscribers.size === 0 && !this.requests.hasConsumers) this.dispose();
      }, this.cacheTtlMs);
    }
  }

  private cancelLifecycleTimers(): void {
    if (this.transitionTimer !== null) clearTimeout(this.transitionTimer);
    if (this.evictionTimer !== null) clearTimeout(this.evictionTimer);
    this.transitionTimer = null;
    this.evictionTimer = null;
  }

  private handleSample(sample: TelemetrySample): void {
    this.rememberSample(sample);
    this.refreshLatestQueries(sample);
    this.lastError = null;
    for (const subscriber of this.subscribers.values()) {
      if (matchesFilters(sample, subscriber.filters)) subscriber.handlers.onSample(sample);
    }
  }

  private handleStateChange(state: TelemetryConnectionState): void {
    this.connectionState = state;
    if (state === "connected") this.lastError = null;
    for (const subscriber of this.subscribers.values()) {
      subscriber.handlers.onStateChange?.(state);
    }
  }

  private handleError(error: Error): void {
    this.lastError = error;
    for (const subscriber of this.subscribers.values()) subscriber.handlers.onError?.(error);
  }

  private handleHeartbeat(serverTime: string): void {
    this.lastHeartbeat = serverTime;
    for (const subscriber of this.subscribers.values()) {
      subscriber.handlers.onHeartbeat?.(serverTime);
    }
  }

  private handleDiagnostic(event: TelemetryDiagnosticEvent): void {
    for (const subscriber of this.subscribers.values()) {
      subscriber.handlers.onDiagnostic?.(event);
    }
  }

  private rememberSample(sample: TelemetrySample): void {
    const key = sampleIdentity(sample);
    const current = this.latestSamples.get(key);
    if (current && capturedAt(current) > capturedAt(sample)) return;

    if (current) this.latestSamples.delete(key);
    this.latestSamples.set(key, sample);
    if (this.latestSamples.size > MAX_LATEST_SAMPLES) {
      const oldestKey = this.latestSamples.keys().next().value as string | undefined;
      if (oldestKey !== undefined) this.latestSamples.delete(oldestKey);
    }
  }

  private refreshLatestQueries(sample: TelemetrySample): void {
    for (const cached of this.latestQueries.values()) {
      if ((cached.query.offset ?? 0) !== 0 || !matchesFilters(sample, cached.query)) continue;

      const identity = sampleIdentity(sample);
      const items = cached.response.items.filter((item) => sampleIdentity(item) !== identity);
      items.push(sample);
      items.sort((left, right) => capturedAt(right) - capturedAt(left));

      const limit = cached.query.limit ?? cached.response.limit;
      cached.response = {
        ...cached.response,
        items: items.slice(0, limit),
        count: Math.max(cached.response.count, items.length),
      };
    }
  }
}

export function getRoutePersistentTelemetryClient(
  websocketUrl: string,
  options: TelemetryWebSocketClientOptions = {},
): RoutePersistentTelemetryClient | TelemetryWebSocketClient {
  if (!canShare(options)) return new TelemetryWebSocketClient(websocketUrl, options);

  const key = sharedClientKey(websocketUrl, options);
  let client = sharedClients.get(key);
  if (!client) {
    const created = new RoutePersistentTelemetryClient(
      new TelemetryWebSocketClient(websocketUrl, options),
      {
        onEvict: () => {
          if (sharedClients.get(key) === created) sharedClients.delete(key);
        },
      },
    );
    client = created;
    sharedClients.set(key, client);
    if (applicationShellRetainCount > 0) client.setApplicationShellRetained(true);
  }
  return client;
}

export function retainTelemetryApplicationShell(): () => void {
  applicationShellRetainCount += 1;
  if (applicationShellRetainCount === 1) {
    for (const client of sharedClients.values()) client.setApplicationShellRetained(true);
  }

  let released = false;
  return () => {
    if (released) return;
    released = true;
    applicationShellRetainCount = Math.max(0, applicationShellRetainCount - 1);
    if (applicationShellRetainCount === 0) {
      for (const client of [...sharedClients.values()]) client.setApplicationShellRetained(false);
      sharedClients.clear();
    }
  };
}

export function resetRoutePersistentTelemetryStateForTests(): void {
  applicationShellRetainCount = 0;
  for (const client of [...sharedClients.values()]) client.dispose();
  sharedClients.clear();
}
