"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { clearAllRefrigerationStructuralCaches } from "@/features/refrigeration/refrigeration-structural-cache";
import { createRuntimeCredentialProvider, signOut as signOutRuntime } from "@/features/security/auth-runtime";
import {
  createAuthenticatedFetch,
  getSecurityCredentials,
  HttpSecuritySessionClient,
  setSecurityCredentials,
  type SecurityMembership,
  type SecuritySession,
  type SecuritySessionDiagnostics,
  type SecuritySessionErrorCode,
  type SecuritySessionFailure,
} from "@/features/security/security-session";
import {
  clearAllMonitoringReadModels,
  invalidateMonitoringReadModel,
  readMonitoringReadModel,
} from "@/lib/monitoring-read-model-cache";
import { getTelemetryRuntimeConfig } from "@/lib/telemetry/runtime-config";

const STORAGE_KEY = "nexolab.selectedOrganizationId";
const SECURITY_SESSION_CACHE_KEY = "security:session";
const SECURITY_SESSION_CACHE = { freshTtlMs: 5_000, staleTtlMs: 5_000, maxEntriesPerScope: 1 } as const;

export type DashboardSecurityState = "demo" | "loading" | "ready" | "unauthenticated" | "forbidden" | "error";

export type DashboardSecurityErrorCode =
  SecuritySessionErrorCode | "INVALID_CONFIGURATION" | "ORGANIZATION_NOT_AVAILABLE";

export type DashboardSecurityModel = {
  mode: "demo" | "live";
  state: DashboardSecurityState;
  session: SecuritySession | null;
  membership: SecurityMembership | null;
  error: string | null;
  errorCode: DashboardSecurityErrorCode | null;
  diagnostics: SecuritySessionDiagnostics | null;
  selectOrganization: (organizationId: string) => void;
  retry: () => void;
  signOut: () => Promise<void>;
};

type Runtime =
  | {
      mode: "demo";
      apiBaseUrl: null;
      configuredOrganizationId: null;
      error: null;
    }
  | {
      mode: "live";
      apiBaseUrl: string | null;
      configuredOrganizationId: string | null;
      error: string | null;
    };

class SecuritySessionLoadError extends Error {
  readonly failure: SecuritySessionFailure;

  constructor(failure: SecuritySessionFailure) {
    super(failure.message);
    this.name = "SecuritySessionLoadError";
    this.failure = failure;
  }
}

function loadRuntime(): Runtime {
  try {
    const config = getTelemetryRuntimeConfig();
    if (config.mode === "demo") {
      return {
        mode: "demo",
        apiBaseUrl: null,
        configuredOrganizationId: null,
        error: null,
      };
    }
    return {
      mode: "live",
      apiBaseUrl: config.apiBaseUrl,
      configuredOrganizationId: process.env.NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID?.trim() || null,
      error: config.apiBaseUrl ? null : "NEXOLAB API URL is required for authenticated dashboard mode.",
    };
  } catch (error) {
    return {
      mode: "live",
      apiBaseUrl: null,
      configuredOrganizationId: null,
      error: error instanceof Error ? error.message : "Invalid dashboard security configuration.",
    };
  }
}

function storedOrganizationId(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY)?.trim() || null;
  } catch {
    return null;
  }
}

function persistOrganizationId(organizationId: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, organizationId);
  } catch {
    // Storage is an optimization only; authorization remains server-side.
  }
}

function clearPersistedOrganizationId(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage cleanup is best effort; server-side authorization remains authoritative.
  }
}

function requestedOrganizationId(configuredOrganizationId: string | null): string | null {
  return storedOrganizationId() ?? getSecurityCredentials().organizationId ?? configuredOrganizationId;
}

function chooseMembership(
  session: SecuritySession,
  configuredOrganizationId: string | null,
): SecurityMembership | null {
  const requested = requestedOrganizationId(configuredOrganizationId);
  if (requested) {
    return session.memberships.find((item) => item.organizationId === requested) ?? null;
  }
  return session.memberships[0] ?? null;
}

function securitySessionScope(apiBaseUrl: string): string {
  return `security-session:${apiBaseUrl}`;
}

function clearRetainedReadModels(): void {
  clearAllMonitoringReadModels();
  clearAllRefrigerationStructuralCaches();
}

async function loadSecuritySession(client: HttpSecuritySessionClient): Promise<SecuritySession> {
  const result = await client.getSession();
  if (!result.ok) throw new SecuritySessionLoadError(result.error);
  return result.value;
}

export function useDashboardSecurity(): DashboardSecurityModel {
  const [runtime] = useState<Runtime>(loadRuntime);
  const [state, setState] = useState<DashboardSecurityState>(() =>
    runtime.mode === "demo" ? "demo" : runtime.error ? "error" : "loading",
  );
  const [session, setSession] = useState<SecuritySession | null>(null);
  const [membership, setMembership] = useState<SecurityMembership | null>(null);
  const [error, setError] = useState<string | null>(runtime.error);
  const [errorCode, setErrorCode] = useState<DashboardSecurityErrorCode | null>(() =>
    runtime.error ? "INVALID_CONFIGURATION" : null,
  );
  const [diagnostics, setDiagnostics] = useState<SecuritySessionDiagnostics | null>(null);
  const [generation, setGeneration] = useState(0);

  const clearFailure = useCallback(() => {
    setError(null);
    setErrorCode(null);
    setDiagnostics(null);
  }, []);

  const retry = useCallback(() => {
    if (runtime.mode === "demo") return;
    if (!runtime.apiBaseUrl) {
      setState("error");
      setError(runtime.error ?? "Authenticated dashboard API is unavailable.");
      setErrorCode("INVALID_CONFIGURATION");
      setDiagnostics(null);
      return;
    }
    invalidateMonitoringReadModel(securitySessionScope(runtime.apiBaseUrl), SECURITY_SESSION_CACHE_KEY);
    setState("loading");
    clearFailure();
    setGeneration((value) => value + 1);
  }, [clearFailure, runtime]);

  useEffect(() => {
    if (runtime.mode === "demo" || !runtime.apiBaseUrl) return;

    let cancelled = false;
    const credentialProvider = createRuntimeCredentialProvider(
      runtime.apiBaseUrl,
      runtime.configuredOrganizationId,
    );
    const authenticatedFetch = createAuthenticatedFetch(fetch.bind(globalThis), credentialProvider);
    const client = new HttpSecuritySessionClient({
      apiBaseUrl: runtime.apiBaseUrl,
      fetchImpl: authenticatedFetch,
    });

    void readMonitoringReadModel(
      securitySessionScope(runtime.apiBaseUrl),
      SECURITY_SESSION_CACHE_KEY,
      () => loadSecuritySession(client),
      SECURITY_SESSION_CACHE,
    )
      .then(async (nextSession) => {
        if (cancelled) return;
        const selected = chooseMembership(nextSession, runtime.configuredOrganizationId);
        if (!selected) {
          setSession(nextSession);
          setMembership(null);
          setError("Вибрана організація відсутня у перевіреній сесії користувача.");
          setErrorCode("ORGANIZATION_NOT_AVAILABLE");
          setDiagnostics(null);
          setState("forbidden");
          return;
        }

        const credentials = await credentialProvider();
        if (cancelled) return;
        setSecurityCredentials({
          accessToken: credentials.accessToken,
          organizationId: selected.organizationId,
        });
        persistOrganizationId(selected.organizationId);
        setSession(nextSession);
        setMembership(selected);
        clearFailure();
        setState("ready");
      })
      .catch((nextError: unknown) => {
        if (cancelled) return;
        if (nextError instanceof SecuritySessionLoadError) {
          setSession(null);
          setMembership(null);
          setError(nextError.failure.message);
          setErrorCode(nextError.failure.code);
          setDiagnostics(nextError.failure.diagnostics);
          setState(
            nextError.failure.code === "AUTHENTICATION_REQUIRED"
              ? "unauthenticated"
              : nextError.failure.code === "ACCESS_DENIED"
                ? "forbidden"
                : "error",
          );
          return;
        }
        setSession(null);
        setMembership(null);
        setError(nextError instanceof Error ? nextError.message : "Не вдалося перевірити захищену сесію.");
        setErrorCode("SESSION_API_ERROR");
        setDiagnostics(null);
        setState("error");
      });

    return () => {
      cancelled = true;
    };
  }, [clearFailure, generation, runtime]);

  const selectOrganization = useCallback(
    (organizationId: string) => {
      if (!session) return;
      const selected = session.memberships.find((item) => item.organizationId === organizationId);
      if (!selected) {
        setError("Вибрана організація відсутня у перевіреній сесії користувача.");
        setErrorCode("ORGANIZATION_NOT_AVAILABLE");
        setDiagnostics(null);
        setState("forbidden");
        return;
      }
      clearRetainedReadModels();
      const credentials = getSecurityCredentials();
      setSecurityCredentials({
        accessToken: credentials.accessToken,
        organizationId: selected.organizationId,
      });
      persistOrganizationId(selected.organizationId);
      setMembership(selected);
      clearFailure();
      setState("ready");
    },
    [clearFailure, session],
  );

  const signOut = useCallback(async () => {
    clearRetainedReadModels();
    await signOutRuntime(runtime.apiBaseUrl);
    clearPersistedOrganizationId();
    setSecurityCredentials({ accessToken: null, organizationId: null });
    setSession(null);
    setMembership(null);
    clearFailure();
    setState(runtime.mode === "demo" ? "demo" : "unauthenticated");
  }, [clearFailure, runtime.apiBaseUrl, runtime.mode]);

  return useMemo(
    () => ({
      mode: runtime.mode,
      state,
      session,
      membership,
      error,
      errorCode,
      diagnostics,
      selectOrganization,
      retry,
      signOut,
    }),
    [
      diagnostics,
      error,
      errorCode,
      membership,
      retry,
      runtime.mode,
      selectOrganization,
      session,
      signOut,
      state,
    ],
  );
}
