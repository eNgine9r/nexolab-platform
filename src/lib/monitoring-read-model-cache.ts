export type MonitoringReadModelFreshness = "missing" | "fresh" | "stale";

export type MonitoringReadModelSnapshot<T> = {
  value: T | null;
  freshness: MonitoringReadModelFreshness;
  refreshing: boolean;
  error: Error | null;
  storedAt: number | null;
};

export type MonitoringReadModelCacheOptions = {
  freshTtlMs?: number;
  staleTtlMs?: number;
  maxEntriesPerScope?: number;
};

type CacheEntry = {
  value: unknown;
  storedAt: number;
  touchedAt: number;
};

type CacheBucket = {
  values: Map<string, CacheEntry>;
  inflight: Map<string, Promise<unknown>>;
  errors: Map<string, Error>;
  listeners: Map<string, Set<() => void>>;
  requestCounts: Map<string, number>;
};

const DEFAULT_FRESH_TTL_MS = 30_000;
const DEFAULT_STALE_TTL_MS = 5 * 60_000;
const DEFAULT_MAX_ENTRIES_PER_SCOPE = 128;
const MAX_SCOPES = 32;
const scopes = new Map<string, CacheBucket>();

function normalizeScope(scope: string): string {
  const normalized = scope.trim();
  if (!normalized) throw new Error("Monitoring read-model cache scope is required.");
  return normalized;
}

function normalizeKey(key: string): string {
  const normalized = key.trim();
  if (!normalized) throw new Error("Monitoring read-model cache key is required.");
  return normalized;
}

function bucket(scope: string): CacheBucket {
  const normalized = normalizeScope(scope);
  let current = scopes.get(normalized);
  if (!current) {
    current = {
      values: new Map(),
      inflight: new Map(),
      errors: new Map(),
      listeners: new Map(),
      requestCounts: new Map(),
    };
    scopes.set(normalized, current);
    trimScopes();
  } else {
    scopes.delete(normalized);
    scopes.set(normalized, current);
  }
  return current;
}

function existingBucket(scope: string): CacheBucket | null {
  return scopes.get(normalizeScope(scope)) ?? null;
}

function optionsWithDefaults(options: MonitoringReadModelCacheOptions) {
  const freshTtlMs = Math.max(0, options.freshTtlMs ?? DEFAULT_FRESH_TTL_MS);
  const staleTtlMs = Math.max(freshTtlMs, options.staleTtlMs ?? DEFAULT_STALE_TTL_MS);
  const maxEntriesPerScope = Math.max(1, options.maxEntriesPerScope ?? DEFAULT_MAX_ENTRIES_PER_SCOPE);
  return { freshTtlMs, staleTtlMs, maxEntriesPerScope };
}

function toError(error: unknown): Error {
  return error instanceof Error ? error : new Error("Monitoring read-model refresh failed.");
}

function notify(current: CacheBucket, key: string): void {
  for (const listener of current.listeners.get(key) ?? []) listener();
}

function trimEntries(current: CacheBucket, maxEntries: number): void {
  if (current.values.size <= maxEntries) return;
  const oldest = [...current.values.entries()]
    .sort((left, right) => left[1].touchedAt - right[1].touchedAt)
    .slice(0, current.values.size - maxEntries);
  for (const [key] of oldest) {
    current.values.delete(key);
    current.errors.delete(key);
    notify(current, key);
  }
}

function trimScopes(): void {
  while (scopes.size > MAX_SCOPES) {
    const oldestScope = scopes.keys().next().value as string | undefined;
    if (oldestScope === undefined) return;
    const current = scopes.get(oldestScope);
    if (current) {
      for (const listeners of current.listeners.values()) {
        for (const listener of listeners) listener();
      }
    }
    scopes.delete(oldestScope);
  }
}

function revalidate<T>(
  scope: string,
  key: string,
  loader: () => Promise<T>,
  options: MonitoringReadModelCacheOptions,
): Promise<T> {
  const current = bucket(scope);
  const normalizedKey = normalizeKey(key);
  const existing = current.inflight.get(normalizedKey) as Promise<T> | undefined;
  if (existing) return existing;

  current.errors.delete(normalizedKey);
  current.requestCounts.set(normalizedKey, (current.requestCounts.get(normalizedKey) ?? 0) + 1);
  notify(current, normalizedKey);

  const request = Promise.resolve()
    .then(loader)
    .then((value) => {
      const now = Date.now();
      current.values.set(normalizedKey, { value, storedAt: now, touchedAt: now });
      current.errors.delete(normalizedKey);
      trimEntries(current, optionsWithDefaults(options).maxEntriesPerScope);
      return value;
    })
    .catch((error: unknown) => {
      current.errors.set(normalizedKey, toError(error));
      throw error;
    })
    .finally(() => {
      current.inflight.delete(normalizedKey);
      notify(current, normalizedKey);
    });

  current.inflight.set(normalizedKey, request);
  notify(current, normalizedKey);
  return request;
}

export function peekMonitoringReadModel<T>(
  scope: string,
  key: string,
  options: MonitoringReadModelCacheOptions = {},
): MonitoringReadModelSnapshot<T> {
  const current = existingBucket(scope);
  const normalizedKey = normalizeKey(key);
  if (!current) {
    return { value: null, freshness: "missing", refreshing: false, error: null, storedAt: null };
  }

  const stored = current.values.get(normalizedKey);
  const error = current.errors.get(normalizedKey) ?? null;
  const refreshing = current.inflight.has(normalizedKey);
  if (!stored) {
    return { value: null, freshness: "missing", refreshing, error, storedAt: null };
  }

  const now = Date.now();
  const { freshTtlMs, staleTtlMs } = optionsWithDefaults(options);
  const age = Math.max(0, now - stored.storedAt);
  if (age > staleTtlMs) {
    current.values.delete(normalizedKey);
    current.errors.delete(normalizedKey);
    return { value: null, freshness: "missing", refreshing, error, storedAt: null };
  }

  stored.touchedAt = now;
  return {
    value: stored.value as T,
    freshness: age <= freshTtlMs ? "fresh" : "stale",
    refreshing,
    error,
    storedAt: stored.storedAt,
  };
}

export async function readMonitoringReadModel<T>(
  scope: string,
  key: string,
  loader: () => Promise<T>,
  options: MonitoringReadModelCacheOptions = {},
): Promise<T> {
  const snapshot = peekMonitoringReadModel<T>(scope, key, options);
  if (snapshot.value !== null && snapshot.freshness === "fresh") return snapshot.value;
  if (snapshot.value !== null && snapshot.freshness === "stale") {
    void revalidate(scope, key, loader, options).catch(() => undefined);
    return snapshot.value;
  }
  return revalidate(scope, key, loader, options);
}

export function refreshMonitoringReadModel<T>(
  scope: string,
  key: string,
  loader: () => Promise<T>,
  options: MonitoringReadModelCacheOptions = {},
): Promise<T> {
  return revalidate(scope, key, loader, options);
}

export function subscribeMonitoringReadModel(scope: string, key: string, listener: () => void): () => void {
  const current = bucket(scope);
  const normalizedKey = normalizeKey(key);
  let listeners = current.listeners.get(normalizedKey);
  if (!listeners) {
    listeners = new Set();
    current.listeners.set(normalizedKey, listeners);
  }
  listeners.add(listener);
  return () => {
    listeners?.delete(listener);
    if (listeners?.size === 0) current.listeners.delete(normalizedKey);
  };
}

export function invalidateMonitoringReadModel(scope: string, keyPrefix?: string): void {
  const current = existingBucket(scope);
  if (!current) return;
  const prefix = keyPrefix?.trim() || null;
  const keys = new Set([...current.values.keys(), ...current.errors.keys(), ...current.listeners.keys()]);
  for (const key of keys) {
    if (prefix !== null && !key.startsWith(prefix)) continue;
    current.values.delete(key);
    current.errors.delete(key);
    notify(current, key);
  }
}

export function clearMonitoringReadModelScope(scope: string): void {
  const normalized = normalizeScope(scope);
  const current = scopes.get(normalized);
  if (!current) return;
  for (const listeners of current.listeners.values()) {
    for (const listener of listeners) listener();
  }
  scopes.delete(normalized);
}

export function clearAllMonitoringReadModels(): void {
  for (const current of scopes.values()) {
    for (const listeners of current.listeners.values()) {
      for (const listener of listeners) listener();
    }
  }
  scopes.clear();
}

export type MonitoringReadModelCacheInspection = {
  scopes: number;
  entries: number;
  inflight: number;
  requestCount: number;
};

export function inspectMonitoringReadModelCache(): MonitoringReadModelCacheInspection {
  let entries = 0;
  let inflight = 0;
  let requestCount = 0;
  for (const current of scopes.values()) {
    entries += current.values.size;
    inflight += current.inflight.size;
    requestCount += [...current.requestCounts.values()].reduce((sum, value) => sum + value, 0);
  }
  return { scopes: scopes.size, entries, inflight, requestCount };
}

export function inspectMonitoringReadModelRequestCount(scope: string, key: string): number {
  return existingBucket(scope)?.requestCounts.get(normalizeKey(key)) ?? 0;
}
