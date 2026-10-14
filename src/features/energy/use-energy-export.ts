"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createAuthenticatedFetch } from "@/features/security/security-session";
import { createRuntimeCredentialProvider } from "@/features/security/supabase-auth";
import { getTelemetryRuntimeConfig } from "@/lib/telemetry/runtime-config";
import {
  EnergyExportClient,
  type EnergyExportCatalog,
  type EnergyExportJob,
  type EnergyExportOptions,
} from "./energy-export-client";

type Scoped<T> = { key: string; value: T };
type RequestScope = {
  key: string;
  client: EnergyExportClient | null;
  active: boolean;
  requests: Set<AbortController>;
  actions: number;
  catalogController: AbortController | null;
  restoreAllowed: boolean;
};
export type EnergyExportController = {
  catalog: EnergyExportCatalog | null;
  catalogStatus: "idle" | "loading" | "ready" | "error";
  job: EnergyExportJob | null;
  busy: boolean;
  error: string | null;
  refreshCatalog: () => Promise<void>;
  preview: (options: EnergyExportOptions) => Promise<boolean>;
  confirm: () => Promise<boolean>;
  cancel: () => Promise<boolean>;
  reset: () => Promise<boolean>;
  refreshJob: () => Promise<boolean>;
  download: () => Promise<boolean>;
};

export function useEnergyExport({
  enabled,
  organizationId,
  securityScopeId,
}: {
  enabled: boolean;
  organizationId: string | null;
  securityScopeId: string | null;
}): EnergyExportController {
  const key = JSON.stringify([organizationId, securityScopeId]);
  const storageKey = `nexolab:energy-export:${key}`;
  const client = useMemo(() => {
    if (!enabled || !organizationId || !securityScopeId) return null;
    try {
      const config = getTelemetryRuntimeConfig();
      if (config.mode !== "live" || !config.apiBaseUrl) return null;
      return new EnergyExportClient(
        createAuthenticatedFetch(fetch.bind(globalThis), createRuntimeCredentialProvider(organizationId)),
        config.apiBaseUrl,
      );
    } catch {
      return null;
    }
  }, [enabled, organizationId, securityScopeId]);
  const scopeRef = useRef<RequestScope | null>(null);
  const [catalogState, setCatalogState] = useState<Scoped<{
    data: EnergyExportCatalog | null;
    status: EnergyExportController["catalogStatus"];
  }> | null>(null);
  const [jobState, setJobState] = useState<Scoped<EnergyExportJob | null> | null>(null);
  const [errorState, setErrorState] = useState<Scoped<string | null> | null>(null);
  const [busyState, setBusyState] = useState<Scoped<number> | null>(null);
  const job = enabled && jobState?.key === key ? jobState.value : null;
  const jobId = job?.job_id;
  const jobStatus = job?.status;

  const saveJob = useCallback(
    (value: EnergyExportJob | null) => {
      setJobState((current) => {
        const previous = current?.key === key ? current.value : null;
        if (value && previous?.job_id === value.job_id) {
          if (previous.phase === "render" && value.phase === "preview") return current;
          if (
            ["canceled", "expired", "failed"].includes(previous.status) &&
            !["canceled", "expired"].includes(value.status)
          )
            return current;
          if (previous.status === "ready" && ["queued", "running", "preview_ready"].includes(value.status))
            return current;
        }
        return { key, value };
      });
      try {
        if (value && !["expired", "canceled"].includes(value.status))
          sessionStorage.setItem(storageKey, value.job_id);
        else sessionStorage.removeItem(storageKey);
      } catch {
        /* Private-browser storage is optional; the server still owns expiry. */
      }
    },
    [key, storageKey],
  );

  useEffect(() => {
    const scope: RequestScope = {
      key,
      client,
      active: true,
      requests: new Set(),
      actions: 0,
      catalogController: null,
      restoreAllowed: true,
    };
    scopeRef.current = scope;
    const controller = new AbortController();
    scope.requests.add(controller);
    void Promise.resolve()
      .then(async () => {
        if (!client || !scope.active || controller.signal.aborted) return;
        setBusyState({ key, value: scope.actions });
        let id: string | null = null;
        try {
          id = sessionStorage.getItem(storageKey);
        } catch {
          return;
        }
        if (!id || !/^[a-f0-9]{32}$/.test(id)) return;
        try {
          const value = await client.job(id, controller.signal);
          if (scope.active && !controller.signal.aborted && scope.restoreAllowed) saveJob(value);
        } catch {
          /* A stale saved ID cannot expose another identity's job. */
        }
      })
      .finally(() => scope.requests.delete(controller));
    return () => {
      scope.active = false;
      for (const request of scope.requests) request.abort();
      scope.requests.clear();
      if (scopeRef.current === scope) scopeRef.current = null;
    };
  }, [client, key, saveJob, storageKey]);

  const run = useCallback(
    async <T>(
      operation: (client: EnergyExportClient, signal: AbortSignal) => Promise<T>,
    ): Promise<T | null> => {
      const scope = scopeRef.current;
      if (!client || !scope || scope.client !== client || scope.key !== key || !scope.active) {
        setErrorState({ key, value: "Сервіс експорту недоступний без авторизованого live runtime." });
        return null;
      }
      const controller = new AbortController();
      scope.requests.add(controller);
      scope.actions += 1;
      setBusyState({ key, value: scope.actions });
      setErrorState({ key, value: null });
      try {
        const result = await operation(client, controller.signal);
        return scope.active && !controller.signal.aborted ? result : null;
      } catch (error) {
        if (scope.active && !controller.signal.aborted)
          setErrorState({
            key,
            value: error instanceof Error ? error.message : "Експорт недоступний. Повторіть запит.",
          });
        return null;
      } finally {
        scope.requests.delete(controller);
        scope.actions -= 1;
        if (scope.active) setBusyState({ key, value: scope.actions });
      }
    },
    [client, key],
  );

  const refreshCatalog = useCallback(async () => {
    const scope = scopeRef.current;
    if (!scope || scope.client !== client || scope.key !== key || !scope.active) return;
    scope.catalogController?.abort();
    const controller = new AbortController();
    scope.catalogController = controller;
    scope.requests.add(controller);
    setCatalogState((current) => ({
      key,
      value: { data: current?.key === key ? current.value.data : null, status: "loading" },
    }));
    try {
      if (!client) throw new Error("Сервіс експорту не налаштовано.");
      const data = await client.catalog(controller.signal);
      if (scope.active && !controller.signal.aborted) {
        setCatalogState({ key, value: { data, status: "ready" } });
        setErrorState({ key, value: null });
      }
    } catch (error) {
      if (scope.active && !controller.signal.aborted) {
        setCatalogState({ key, value: { data: null, status: "error" } });
        setErrorState({
          key,
          value: error instanceof Error ? error.message : "Не вдалося отримати перелік лічильників.",
        });
      }
    } finally {
      scope.requests.delete(controller);
    }
  }, [client, key]);

  useEffect(() => {
    if (!client || !jobId || !jobStatus || !["queued", "running"].includes(jobStatus)) return;
    const scope = scopeRef.current;
    if (!scope || scope.client !== client || scope.key !== key || !scope.active) return;
    const id = jobId;
    const controller = new AbortController();
    scope.requests.add(controller);
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      let delay = 1000;
      try {
        const value = await client.job(id, controller.signal);
        if (scope.active && !controller.signal.aborted) {
          setJobState((current) =>
            current?.key === key &&
            current.value?.job_id === id &&
            current.value.phase === value.phase &&
            ["queued", "running"].includes(current.value.status)
              ? { key, value }
              : current,
          );
          setErrorState({ key, value: null });
        }
      } catch (error) {
        delay = 5000;
        if (scope.active && !controller.signal.aborted)
          setErrorState({
            key,
            value: error instanceof Error ? error.message : "Не вдалося перевірити стан експорту.",
          });
      }
      if (scope.active && !controller.signal.aborted) timer = setTimeout(() => void poll(), delay);
    };
    void Promise.resolve().then(poll);
    return () => {
      controller.abort();
      clearTimeout(timer);
      scope.requests.delete(controller);
    };
  }, [client, jobId, jobStatus, key]);

  const preview = useCallback(
    async (options: EnergyExportOptions) => {
      const scope = scopeRef.current;
      if (!scope || scope.key !== key || !scope.active) return false;
      scope.restoreAllowed = false;
      const result = await run(async (api, signal) => {
        if (job && ["queued", "running", "preview_ready"].includes(job.status)) {
          const canceled = await api.action(job.job_id, "cancel", signal);
          if (scope.active && !signal.aborted) saveJob(canceled);
        }
        return api.preview(options, signal);
      });
      if (result) saveJob(result);
      return result !== null;
    },
    [job, key, run, saveJob],
  );
  const action = useCallback(
    async (kind: "start" | "cancel") => {
      if (!job) return false;
      const result = await run((api, signal) => api.action(job.job_id, kind, signal));
      if (result) saveJob(result);
      return result !== null;
    },
    [job, run, saveJob],
  );
  const reset = useCallback(async () => {
    const scope = scopeRef.current;
    if (!scope || scope.key !== key || !scope.active) return false;
    scope.restoreAllowed = false;
    if (job && ["queued", "running", "preview_ready"].includes(job.status) && !(await action("cancel")))
      return false;
    saveJob(null);
    setErrorState({ key, value: null });
    return true;
  }, [action, job, key, saveJob]);
  const refreshJob = useCallback(async () => {
    if (!job) return false;
    const result = await run((api, signal) => api.job(job.job_id, signal));
    if (result) saveJob(result);
    return result !== null;
  }, [job, run, saveJob]);
  const download = useCallback(async () => {
    if (!job || job.status !== "ready") return false;
    const url = await run((api, signal) => api.downloadUrl(job.job_id, signal));
    if (!url) return false;
    const link = document.createElement("a");
    link.href = url;
    link.download = `nexolab-energy.${job.options.format}`;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    document.body.append(link);
    link.click();
    link.remove();
    return true;
  }, [job, run]);
  return {
    catalog: enabled && catalogState?.key === key ? catalogState.value.data : null,
    catalogStatus: enabled && catalogState?.key === key ? catalogState.value.status : "idle",
    job,
    busy: enabled && busyState?.key === key && busyState.value > 0,
    error: enabled && errorState?.key === key ? errorState.value : null,
    refreshCatalog,
    preview,
    confirm: () => action("start"),
    cancel: () => action("cancel"),
    reset,
    refreshJob,
    download,
  };
}
