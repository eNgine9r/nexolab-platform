"use client";

import { useCallback } from "react";

import { loadLiveDashboardInventory } from "@/features/live-dashboards/inventory";
import { createLiveDashboardInventoryClient } from "@/features/live-dashboards/inventory-client";
import type { LiveDashboardInventoryItem } from "@/features/live-dashboards/types";
import { useMonitoringReadModel } from "@/hooks/use-monitoring-read-model";

export type LiveDashboardInventoryStatus = "idle" | "loading" | "ready" | "error";

export interface LiveDashboardInventoryModel {
  items: LiveDashboardInventoryItem[];
  status: LiveDashboardInventoryStatus;
  error: Error | null;
  retry: () => void;
}

const DEFAULT_SCOPE = "__default_organization__";
const INVENTORY_CACHE_KEY = "live-dashboard:channel-inventory";
const INVENTORY_CACHE = { freshTtlMs: 10_000, staleTtlMs: 60_000, maxEntriesPerScope: 8 } as const;

export function useLiveDashboardInventory({
  enabled,
  organizationId,
}: {
  enabled: boolean;
  organizationId: string | null;
}): LiveDashboardInventoryModel {
  const scopeKey = organizationId ?? DEFAULT_SCOPE;
  const load = useCallback(async () => {
    const client = createLiveDashboardInventoryClient(organizationId);
    return loadLiveDashboardInventory(client);
  }, [organizationId]);
  const inventory = useMonitoringReadModel({
    enabled,
    scope: `live-dashboard-inventory:${scopeKey}`,
    key: INVENTORY_CACHE_KEY,
    load,
    cache: INVENTORY_CACHE,
  });

  return {
    items: inventory.value ?? [],
    status: mapStatus(inventory.status),
    error: inventory.error,
    retry: inventory.retry,
  };
}

function mapStatus(status: ReturnType<typeof useMonitoringReadModel<LiveDashboardInventoryItem[]>>["status"]): LiveDashboardInventoryStatus {
  if (status === "idle") return "idle";
  if (status === "loading") return "loading";
  if (status === "error") return "error";
  return "ready";
}
