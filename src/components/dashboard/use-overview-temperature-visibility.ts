"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

const STORAGE_PREFIX = "nexolab.overview.temperature-visible";
const SCHEMA_VERSION = 1;

type StoredPreference = {
  schemaVersion: number;
  channelIds: string[];
};

export type OverviewTemperatureVisibility = {
  visibleChannelIds: string[];
  loaded: boolean;
  setVisibleChannelIds: (channelIds: readonly string[]) => void;
  showAll: () => void;
};

type Options = {
  enabled: boolean;
  organizationId: string | null;
  monitoredChannelIds: readonly string[];
};

function storageKey(organizationId: string | null): string {
  return `${STORAGE_PREFIX}.${organizationId ?? "default"}`;
}

function normalizeChannelIds(channelIds: readonly string[], allowed: ReadonlySet<string>): string[] {
  return [...new Set(channelIds)]
    .filter((channelId) => allowed.has(channelId))
    .sort((left, right) => left.localeCompare(right, undefined, { numeric: true }));
}

function readPreference(organizationId: string | null): string[] | null {
  try {
    const raw = window.localStorage.getItem(storageKey(organizationId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredPreference>;
    if (parsed.schemaVersion !== SCHEMA_VERSION || !Array.isArray(parsed.channelIds)) return null;
    if (!parsed.channelIds.every((item) => typeof item === "string")) return null;
    return [...new Set(parsed.channelIds)];
  } catch {
    return null;
  }
}

function writePreference(organizationId: string | null, channelIds: readonly string[]): void {
  try {
    const value: StoredPreference = { schemaVersion: SCHEMA_VERSION, channelIds: [...channelIds] };
    window.localStorage.setItem(storageKey(organizationId), JSON.stringify(value));
  } catch {
    // Display preference failure must never affect acquisition or telemetry delivery.
  }
}

export function useOverviewTemperatureVisibility(options: Options): OverviewTemperatureVisibility {
  const monitoredKey = [...new Set(options.monitoredChannelIds)].sort().join(",");
  const monitored = useMemo(() => (monitoredKey ? monitoredKey.split(",") : []), [monitoredKey]);
  const monitoredSet = useMemo(() => new Set(monitored), [monitored]);
  const [preference, setPreference] = useState<string[] | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void Promise.resolve().then(() => {
      if (cancelled) return;
      if (!options.enabled) {
        setPreference(null);
        setLoaded(true);
        return;
      }
      setPreference(readPreference(options.organizationId));
      setLoaded(true);
    });
    return () => {
      cancelled = true;
    };
  }, [options.enabled, options.organizationId]);

  const visibleChannelIds = useMemo(
    () =>
      options.enabled
        ? preference === null
          ? monitored
          : normalizeChannelIds(preference, monitoredSet)
        : [],
    [monitored, monitoredSet, options.enabled, preference],
  );

  const setVisibleChannelIds = useCallback(
    (channelIds: readonly string[]) => {
      const next = normalizeChannelIds(channelIds, monitoredSet);
      setPreference(next);
      writePreference(options.organizationId, next);
    },
    [monitoredSet, options.organizationId],
  );

  const showAll = useCallback(() => {
    setVisibleChannelIds(monitored);
  }, [monitored, setVisibleChannelIds]);

  return { visibleChannelIds, loaded, setVisibleChannelIds, showAll };
}
