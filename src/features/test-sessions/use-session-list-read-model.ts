"use client";

import { useCallback } from "react";

import { getSecurityCredentials } from "@/features/security/security-session";
import { useMonitoringReadModel, type MonitoringReadModel } from "@/hooks/use-monitoring-read-model";
import { createSessionApiClient, type SessionListQuery } from "@/lib/sessions/api-client";
import type { SessionPage } from "@/lib/sessions/types";
import { invalidateMonitoringReadModel } from "@/lib/monitoring-read-model-cache";

const DEFAULT_ORGANIZATION_SCOPE = "__default_organization__";
const SESSION_LIST_PREFIX = "sessions:list:";
const SESSION_LIST_CACHE = {
  freshTtlMs: 10_000,
  staleTtlMs: 60_000,
  maxEntriesPerScope: 24,
} as const;

export type UseSessionListReadModelInput = {
  enabled?: boolean;
  organizationId?: string | null;
  query?: SessionListQuery;
};

export function useSessionListReadModel({
  enabled = true,
  organizationId = null,
  query = {},
}: UseSessionListReadModelInput = {}): MonitoringReadModel<SessionPage> {
  const state = query.state;
  const nodeId = query.nodeId;
  const limit = query.limit ?? 100;
  const offset = query.offset ?? 0;
  const resolvedOrganizationId = resolveOrganizationId(organizationId);
  const load = useCallback(
    () => createSessionApiClient().listSessions({ state, nodeId, limit, offset }),
    [limit, nodeId, offset, state],
  );

  return useMonitoringReadModel({
    enabled,
    scope: sessionReadModelScope(resolvedOrganizationId),
    key: sessionListKey({ state, nodeId, limit, offset }),
    load,
    cache: SESSION_LIST_CACHE,
  });
}

export function invalidateSessionListReadModels(organizationId?: string | null): void {
  invalidateMonitoringReadModel(
    sessionReadModelScope(resolveOrganizationId(organizationId ?? null)),
    SESSION_LIST_PREFIX,
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

function sessionReadModelScope(organizationId: string): string {
  return `sessions:${organizationId}`;
}

function sessionListKey(query: Required<Pick<SessionListQuery, "limit" | "offset">> & SessionListQuery): string {
  return `${SESSION_LIST_PREFIX}state=${query.state ?? "all"}|node=${query.nodeId ?? "all"}|limit=${query.limit}|offset=${query.offset}`;
}
