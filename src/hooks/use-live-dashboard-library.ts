"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  createLiveDashboardApiClient,
  LiveDashboardClientError,
  type LiveDashboardApiClient,
} from "@/features/live-dashboards/api-client";
import {
  draftToWrite,
  duplicateDashboardDraft,
  liveDashboardEtag,
} from "@/features/live-dashboards/model";
import type {
  LiveDashboard,
  LiveDashboardDraft,
  LiveDashboardVersioned,
} from "@/features/live-dashboards/types";

export type LiveDashboardLibraryStatus = "idle" | "loading" | "ready" | "forbidden" | "error";

export interface LiveDashboardConflict {
  draft: LiveDashboardDraft;
  server: LiveDashboardVersioned | null;
  expectedVersion: number | null;
  actualVersion: number | null;
}

export interface LiveDashboardSaveResult {
  saved: LiveDashboardVersioned | null;
  conflict: LiveDashboardConflict | null;
}

export interface LiveDashboardLibraryModel {
  dashboards: LiveDashboard[];
  status: LiveDashboardLibraryStatus;
  error: Error | null;
  includeArchived: boolean;
  setIncludeArchived: (value: boolean) => void;
  refresh: () => void;
  get: (dashboardId: string, signal?: AbortSignal) => Promise<LiveDashboardVersioned>;
  save: (draft: LiveDashboardDraft) => Promise<LiveDashboardSaveResult>;
  duplicate: (dashboard: LiveDashboard) => Promise<LiveDashboardVersioned>;
  archive: (dashboard: LiveDashboard) => Promise<void>;
}

interface ClientResult {
  client: LiveDashboardApiClient | null;
  error: Error | null;
}

const DEFAULT_SCOPE = "__default_organization__";

function upsertDashboard(current: LiveDashboard[], dashboard: LiveDashboard): LiveDashboard[] {
  const without = current.filter((item) => item.id !== dashboard.id);
  return [dashboard, ...without].sort(
    (left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at),
  );
}

function classifyStatus(error: unknown): LiveDashboardLibraryStatus {
  return error instanceof LiveDashboardClientError && error.status === 403 ? "forbidden" : "error";
}

export function useLiveDashboardLibrary({
  enabled,
  organizationId,
}: {
  enabled: boolean;
  organizationId: string | null;
}): LiveDashboardLibraryModel {
  const scopeKey = enabled ? (organizationId ?? DEFAULT_SCOPE) : null;
  const [activeScopeKey, setActiveScopeKey] = useState<string | null>(null);
  const [dashboards, setDashboards] = useState<LiveDashboard[]>([]);
  const [status, setStatus] = useState<LiveDashboardLibraryStatus>("idle");
  const [error, setError] = useState<Error | null>(null);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [generation, setGeneration] = useState(0);

  const clientResult = useMemo<ClientResult>(() => {
    if (!enabled) return { client: null, error: null };
    try {
      return { client: createLiveDashboardApiClient(organizationId), error: null };
    } catch (nextError) {
      return {
        client: null,
        error:
          nextError instanceof Error
            ? nextError
            : new Error("Live Dashboard API configuration failed."),
      };
    }
  }, [enabled, organizationId]);
  const client = clientResult.client;

  const refresh = useCallback(() => {
    if (enabled) setGeneration((value) => value + 1);
  }, [enabled]);

  useEffect(() => {
    if (!enabled || scopeKey === null) return;

    const controller = new AbortController();
    void Promise.resolve().then(() => {
      if (controller.signal.aborted) return;
      setActiveScopeKey(scopeKey);
      setDashboards([]);
      if (!client) {
        setError(clientResult.error);
        setStatus("error");
        return;
      }
      setStatus("loading");
      setError(null);
    });

    if (!client) return () => controller.abort();

    void client
      .list({ includeArchived, limit: 100, offset: 0 }, controller.signal)
      .then((page) => {
        setDashboards(page.items);
        setStatus("ready");
      })
      .catch((nextError: unknown) => {
        if (controller.signal.aborted) return;
        setError(
          nextError instanceof Error ? nextError : new Error("Live Dashboard library failed."),
        );
        setStatus(classifyStatus(nextError));
      });
    return () => controller.abort();
  }, [client, clientResult.error, enabled, generation, includeArchived, scopeKey]);

  const get = useCallback(
    async (dashboardId: string, signal?: AbortSignal): Promise<LiveDashboardVersioned> => {
      if (!client) throw new Error("Live Dashboard API is unavailable.");
      return client.get(dashboardId, signal);
    },
    [client],
  );

  const save = useCallback(
    async (draft: LiveDashboardDraft): Promise<LiveDashboardSaveResult> => {
      if (!client) throw new Error("Live Dashboard API is unavailable.");
      try {
        const saved = draft.id
          ? await client.update(
              draft.id,
              draftToWrite(draft),
              draft.etag ?? liveDashboardEtag(draft.version ?? 1),
            )
          : await client.create(draftToWrite(draft));
        setDashboards((current) => upsertDashboard(current, saved.value));
        return { saved, conflict: null };
      } catch (nextError) {
        if (
          draft.id &&
          nextError instanceof LiveDashboardClientError &&
          nextError.code === "live_dashboard_version_conflict"
        ) {
          let server: LiveDashboardVersioned | null = null;
          try {
            server = await client.get(draft.id);
          } catch {
            server = null;
          }
          return {
            saved: null,
            conflict: {
              draft,
              server,
              expectedVersion: nextError.expectedVersion,
              actualVersion: nextError.actualVersion,
            },
          };
        }
        throw nextError;
      }
    },
    [client],
  );

  const duplicate = useCallback(
    async (dashboard: LiveDashboard): Promise<LiveDashboardVersioned> => {
      if (!client) throw new Error("Live Dashboard API is unavailable.");
      const created = await client.create(
        draftToWrite(duplicateDashboardDraft(dashboard)),
        "Duplicate Live Dashboard",
      );
      setDashboards((current) => upsertDashboard(current, created.value));
      return created;
    },
    [client],
  );

  const archive = useCallback(
    async (dashboard: LiveDashboard): Promise<void> => {
      if (!client) throw new Error("Live Dashboard API is unavailable.");
      await client.archive(dashboard.id, liveDashboardEtag(dashboard.version));
      if (includeArchived) {
        const archived = await client.get(dashboard.id);
        setDashboards((current) => upsertDashboard(current, archived.value));
      } else {
        setDashboards((current) => current.filter((item) => item.id !== dashboard.id));
      }
    },
    [client, includeArchived],
  );

  const visible = enabled && scopeKey !== null && activeScopeKey === scopeKey;
  return {
    dashboards: visible ? dashboards : [],
    status: visible ? status : enabled ? "loading" : "idle",
    error: visible ? error : null,
    includeArchived,
    setIncludeArchived,
    refresh,
    get,
    save,
    duplicate,
    archive,
  };
}
