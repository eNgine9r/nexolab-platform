"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { createAuthenticatedFetch } from "@/features/security/security-session";
import { createRuntimeCredentialProvider } from "@/features/security/supabase-auth";

const CONTROL_URL = "/api/device-agent/xjp60d";
const STORAGE_PREFIX = "nexolab.xjp60d.active-points";

export type Xjp60dDiscoveryPoint = {
  channel_id: string;
  unit_id: number;
  channel: number;
  quality: "valid" | "sensor_error" | "communication_error";
  value: number | null;
  unit: string;
  alarm: "low" | "high" | null;
  raw_status: number | null;
};

export type Xjp60dDiscoveryResult = {
  scanned_at: string;
  duration_ms: number;
  controller_count: number;
  reachable_controller_count: number;
  available_points: Xjp60dDiscoveryPoint[];
  unavailable_points: Xjp60dDiscoveryPoint[];
  controller_errors: Array<{ unit_id: number; message: string }>;
};

export type Xjp60dConfiguration = {
  node_id: string;
  active_points: string[];
  discovery_units: number[];
  last_discovery: Xjp60dDiscoveryResult | null;
};

export type Xjp60dSensorManagement = {
  configuration: Xjp60dConfiguration | null;
  activeChannelIds: string[];
  isLoading: boolean;
  isDiscovering: boolean;
  isSaving: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  discover: () => Promise<Xjp60dDiscoveryResult | null>;
  save: (points: readonly string[]) => Promise<boolean>;
};

type Options = {
  enabled: boolean;
  organizationId: string | null;
};

function storageKey(organizationId: string | null): string {
  return `${STORAGE_PREFIX}.${organizationId ?? "default"}`;
}

function readCachedPoints(organizationId: string | null): string[] {
  try {
    const value = window.localStorage.getItem(storageKey(organizationId));
    if (!value) return [];
    const parsed = JSON.parse(value) as unknown;
    return Array.isArray(parsed)
      ? parsed.filter((item): item is string => typeof item === "string" && /^\d{1,3}-0[1-6]$/.test(item))
      : [];
  } catch {
    return [];
  }
}

function writeCachedPoints(organizationId: string | null, points: readonly string[]): void {
  try {
    window.localStorage.setItem(storageKey(organizationId), JSON.stringify(points));
  } catch {
    // Runtime configuration remains authoritative; cache is only for first paint.
  }
}

async function readError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as {
      detail?: string | { message?: string };
    };
    if (typeof payload.detail === "string") return payload.detail;
    if (payload.detail?.message) return payload.detail.message;
  } catch {
    // Fall through to a stable operator-facing error.
  }
  return `Операція завершилась з HTTP ${response.status}.`;
}

function normalizeConfiguration(value: unknown): Xjp60dConfiguration {
  if (!value || typeof value !== "object") throw new Error("Некоректна відповідь Device Agent.");
  const record = value as Partial<Xjp60dConfiguration>;
  if (
    typeof record.node_id !== "string" ||
    !Array.isArray(record.active_points) ||
    !Array.isArray(record.discovery_units)
  ) {
    throw new Error("Некоректна конфігурація Device Agent.");
  }
  return {
    node_id: record.node_id,
    active_points: record.active_points.filter(
      (item): item is string => typeof item === "string" && /^\d{1,3}-0[1-6]$/.test(item),
    ),
    discovery_units: record.discovery_units.filter(
      (item): item is number => Number.isInteger(item) && item >= 1 && item <= 247,
    ),
    last_discovery: record.last_discovery ?? null,
  };
}

export function useXjp60dSensorManagement(options: Options): Xjp60dSensorManagement {
  const [configuration, setConfiguration] = useState<Xjp60dConfiguration | null>(null);
  const [cachedPoints, setCachedPoints] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(options.enabled);
  const [isDiscovering, setIsDiscovering] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const authenticatedFetch = useMemo(
    () =>
      createAuthenticatedFetch(
        fetch.bind(globalThis),
        createRuntimeCredentialProvider(options.organizationId),
      ),
    [options.organizationId],
  );

  useEffect(() => {
    if (!options.enabled) {
      setConfiguration(null);
      setCachedPoints([]);
      setIsLoading(false);
      setError(null);
      return;
    }
    setCachedPoints(readCachedPoints(options.organizationId));
  }, [options.enabled, options.organizationId]);

  const refresh = useCallback(async () => {
    if (!options.enabled) return;
    setIsLoading(true);
    setError(null);
    try {
      const response = await authenticatedFetch(CONTROL_URL, {
        method: "GET",
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(await readError(response));
      const next = normalizeConfiguration((await response.json()) as unknown);
      setConfiguration(next);
      setCachedPoints(next.active_points);
      writeCachedPoints(options.organizationId, next.active_points);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Не вдалося отримати список датчиків.");
    } finally {
      setIsLoading(false);
    }
  }, [authenticatedFetch, options.enabled, options.organizationId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const discover = useCallback(async () => {
    if (!options.enabled) return null;
    setIsDiscovering(true);
    setError(null);
    try {
      const response = await authenticatedFetch(CONTROL_URL, {
        method: "POST",
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(await readError(response));
      const next = normalizeConfiguration((await response.json()) as unknown);
      setConfiguration(next);
      setCachedPoints(next.active_points);
      writeCachedPoints(options.organizationId, next.active_points);
      return next.last_discovery;
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Не вдалося виконати пошук датчиків.");
      return null;
    } finally {
      setIsDiscovering(false);
    }
  }, [authenticatedFetch, options.enabled, options.organizationId]);

  const save = useCallback(
    async (points: readonly string[]) => {
      if (!options.enabled) return false;
      setIsSaving(true);
      setError(null);
      try {
        const response = await authenticatedFetch(CONTROL_URL, {
          method: "PUT",
          cache: "no-store",
          headers: { Accept: "application/json", "Content-Type": "application/json" },
          body: JSON.stringify({ points: [...new Set(points)].sort() }),
        });
        if (!response.ok) throw new Error(await readError(response));
        const next = normalizeConfiguration((await response.json()) as unknown);
        setConfiguration(next);
        setCachedPoints(next.active_points);
        writeCachedPoints(options.organizationId, next.active_points);
        return true;
      } catch (nextError) {
        setError(nextError instanceof Error ? nextError.message : "Не вдалося зберегти список датчиків.");
        return false;
      } finally {
        setIsSaving(false);
      }
    },
    [authenticatedFetch, options.enabled, options.organizationId],
  );

  return {
    configuration,
    activeChannelIds: configuration?.active_points ?? cachedPoints,
    isLoading,
    isDiscovering,
    isSaving,
    error,
    refresh,
    discover,
    save,
  };
}
