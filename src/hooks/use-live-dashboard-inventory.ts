"use client";

import { useCallback, useEffect, useState } from "react";

import { loadLiveDashboardInventory } from "@/features/live-dashboards/inventory";
import type { LiveDashboardInventoryItem } from "@/features/live-dashboards/types";
import { createRuntimeCredentialProvider } from "@/features/security/auth-runtime";
import { createAuthenticatedFetch } from "@/features/security/security-session";
import { createTelemetryAdapter } from "@/lib/telemetry/create-adapter";
import { getTelemetryRuntimeConfig } from "@/lib/telemetry/runtime-config";

export type LiveDashboardInventoryStatus = "idle" | "loading" | "ready" | "error";

export interface LiveDashboardInventoryModel {
  items: LiveDashboardInventoryItem[];
  status: LiveDashboardInventoryStatus;
  error: Error | null;
  retry: () => void;
}

const DEFAULT_SCOPE = "__default_organization__";

export function useLiveDashboardInventory({
  enabled,
  organizationId,
}: {
  enabled: boolean;
  organizationId: string | null;
}): LiveDashboardInventoryModel {
  const scopeKey = enabled ? (organizationId ?? DEFAULT_SCOPE) : null;
  const [activeScopeKey, setActiveScopeKey] = useState<string | null>(null);
  const [items, setItems] = useState<LiveDashboardInventoryItem[]>([]);
  const [status, setStatus] = useState<LiveDashboardInventoryStatus>("idle");
  const [error, setError] = useState<Error | null>(null);
  const [generation, setGeneration] = useState(0);

  const retry = useCallback(() => {
    if (enabled) setGeneration((value) => value + 1);
  }, [enabled]);

  useEffect(() => {
    if (!enabled || scopeKey === null) return;

    const controller = new AbortController();
    void Promise.resolve().then(() => {
      if (controller.signal.aborted) return;
      setActiveScopeKey(scopeKey);
      setStatus("loading");
      setError(null);
    });

    try {
      const config = getTelemetryRuntimeConfig();
      if (config.mode !== "live" || !config.apiBaseUrl) {
        throw new Error("Live Dashboard inventory requires configured live mode.");
      }
      const credentials = createRuntimeCredentialProvider(config.apiBaseUrl, organizationId);
      const adapter = createTelemetryAdapter(config, {
        rest: { fetch: createAuthenticatedFetch(fetch.bind(globalThis), credentials) },
        websocket: { credentials },
      });
      void loadLiveDashboardInventory(adapter, controller.signal)
        .then((nextItems) => {
          setItems(nextItems);
          setStatus("ready");
        })
        .catch((nextError: unknown) => {
          if (controller.signal.aborted) return;
          setError(
            nextError instanceof Error
              ? nextError
              : new Error("Channel inventory failed to load."),
          );
          setStatus("error");
        });
    } catch (nextError) {
      void Promise.resolve().then(() => {
        if (controller.signal.aborted) return;
        setError(
          nextError instanceof Error
            ? nextError
            : new Error("Channel inventory configuration failed."),
        );
        setStatus("error");
      });
    }

    return () => controller.abort();
  }, [enabled, generation, organizationId, scopeKey]);

  const visible = enabled && scopeKey !== null && activeScopeKey === scopeKey;
  return {
    items: visible ? items : [],
    status: visible ? status : enabled ? "loading" : "idle",
    error: visible ? error : null,
    retry,
  };
}
