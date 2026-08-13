"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  peekMonitoringReadModel,
  readMonitoringReadModel,
  refreshMonitoringReadModel,
  subscribeMonitoringReadModel,
  type MonitoringReadModelCacheOptions,
  type MonitoringReadModelSnapshot,
} from "@/lib/monitoring-read-model-cache";

export type MonitoringReadModelStatus = "idle" | "loading" | "ready" | "refreshing" | "stale" | "error";

export type UseMonitoringReadModelOptions<T> = {
  enabled: boolean;
  scope: string;
  key: string;
  load: () => Promise<T>;
  cache?: MonitoringReadModelCacheOptions;
};

export type MonitoringReadModel<T> = {
  value: T | null;
  status: MonitoringReadModelStatus;
  error: Error | null;
  freshness: MonitoringReadModelSnapshot<T>["freshness"];
  retry: () => void;
};

function emptySnapshot<T>(): MonitoringReadModelSnapshot<T> {
  return {
    value: null,
    freshness: "missing",
    refreshing: false,
    error: null,
    storedAt: null,
  };
}

function statusFor<T>(enabled: boolean, snapshot: MonitoringReadModelSnapshot<T>): MonitoringReadModelStatus {
  if (!enabled) return "idle";
  if (snapshot.value === null) return snapshot.error ? "error" : "loading";
  if (snapshot.error) return "error";
  if (snapshot.refreshing) return "refreshing";
  if (snapshot.freshness === "stale") return "stale";
  return "ready";
}

export function useMonitoringReadModel<T>({
  enabled,
  scope,
  key,
  load,
  cache = {},
}: UseMonitoringReadModelOptions<T>): MonitoringReadModel<T> {
  const freshTtlMs = cache.freshTtlMs;
  const staleTtlMs = cache.staleTtlMs;
  const maxEntriesPerScope = cache.maxEntriesPerScope;
  const stableCache = useMemo(
    () => ({ freshTtlMs, staleTtlMs, maxEntriesPerScope }),
    [freshTtlMs, maxEntriesPerScope, staleTtlMs],
  );
  const [snapshot, setSnapshot] = useState<MonitoringReadModelSnapshot<T>>(() =>
    enabled ? peekMonitoringReadModel<T>(scope, key, stableCache) : emptySnapshot<T>(),
  );

  const synchronize = useCallback(() => {
    setSnapshot(enabled ? peekMonitoringReadModel<T>(scope, key, stableCache) : emptySnapshot<T>());
  }, [enabled, key, scope, stableCache]);

  const retry = useCallback(() => {
    if (!enabled) return;
    void refreshMonitoringReadModel(scope, key, load, stableCache)
      .catch(() => undefined)
      .finally(synchronize);
  }, [enabled, key, load, scope, stableCache, synchronize]);

  useEffect(() => {
    if (!enabled) {
      setSnapshot(emptySnapshot<T>());
      return;
    }

    let active = true;
    const sync = () => {
      if (active) synchronize();
    };
    const unsubscribe = subscribeMonitoringReadModel(scope, key, sync);
    sync();
    void readMonitoringReadModel(scope, key, load, stableCache)
      .catch(() => undefined)
      .finally(sync);

    return () => {
      active = false;
      unsubscribe();
    };
  }, [enabled, key, load, scope, stableCache, synchronize]);

  return {
    value: enabled ? snapshot.value : null,
    status: statusFor(enabled, snapshot),
    error: enabled ? snapshot.error : null,
    freshness: enabled ? snapshot.freshness : "missing",
    retry,
  };
}
