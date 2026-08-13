"use client";

import { useCallback } from "react";

import { getSecurityCredentials } from "@/features/security/security-session";
import { useMonitoringReadModel, type MonitoringReadModel } from "@/hooks/use-monitoring-read-model";
import { createAlertApiClient } from "@/lib/alerts/api-client";
import type { AlertInstance } from "@/lib/alerts/types";
import { invalidateMonitoringReadModel } from "@/lib/monitoring-read-model-cache";

const DEFAULT_ORGANIZATION_SCOPE = "__default_organization__";
const OVERVIEW_ALERTS_KEY = "overview:alerts:active-acknowledged";
const OVERVIEW_ALERTS_CACHE = {
  freshTtlMs: 5_000,
  staleTtlMs: 30_000,
  maxEntriesPerScope: 4,
} as const;

export function useOverviewAlertsReadModel({
  enabled,
  organizationId,
}: {
  enabled: boolean;
  organizationId: string | null;
}): MonitoringReadModel<AlertInstance[]> {
  const resolvedOrganizationId = resolveOrganizationId(organizationId);
  const load = useCallback(async () => {
    const client = createAlertApiClient();
    const [active, acknowledged] = await Promise.all([
      client.listAlerts({ state: "active", limit: 20 }),
      client.listAlerts({ state: "acknowledged", limit: 20 }),
    ]);
    return [...active.items, ...acknowledged.items]
      .sort((left, right) => new Date(right.triggered_at).getTime() - new Date(left.triggered_at).getTime())
      .slice(0, 8);
  }, []);

  return useMonitoringReadModel({
    enabled,
    scope: overviewAlertsScope(resolvedOrganizationId),
    key: OVERVIEW_ALERTS_KEY,
    load,
    cache: OVERVIEW_ALERTS_CACHE,
  });
}

export function invalidateOverviewAlertsReadModel(organizationId?: string | null): void {
  invalidateMonitoringReadModel(
    overviewAlertsScope(resolveOrganizationId(organizationId ?? null)),
    OVERVIEW_ALERTS_KEY,
  );
}

function resolveOrganizationId(organizationId: string | null): string {
  return (
    organizationId?.trim() ||
    getSecurityCredentials().organizationId?.trim() ||
    process.env.NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID?.trim() ||
    DEFAULT_ORGANIZATION_SCOPE
  );
}

function overviewAlertsScope(organizationId: string): string {
  return `overview-alerts:${organizationId}`;
}
