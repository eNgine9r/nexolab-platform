"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  createAuthenticatedFetch,
  getSecurityCredentials,
  HttpSecuritySessionClient,
  setSecurityCredentials,
  type SecurityMembership,
  type SecuritySession,
} from "@/features/security/security-session";
import {
  createRuntimeCredentialProvider,
  signOut as signOutSupabase,
} from "@/features/security/supabase-auth";
import { getTelemetryRuntimeConfig } from "@/lib/telemetry/runtime-config";

const STORAGE_KEY = "nexolab.selectedOrganizationId";

export type DashboardSecurityState = "demo" | "loading" | "ready" | "unauthenticated" | "forbidden" | "error";

export type DashboardSecurityModel = {
  mode: "demo" | "live";
  state: DashboardSecurityState;
  session: SecuritySession | null;
  membership: SecurityMembership | null;
  error: string | null;
  selectOrganization: (organizationId: string) => void;
  retry: () => void;
  signOut: () => Promise<void>;
};

type Runtime =
  | { mode: "demo"; apiBaseUrl: null; configuredOrganizationId: null; error: null }
  | {
      mode: "live";
      apiBaseUrl: string | null;
      configuredOrganizationId: string | null;
      error: string | null;
    };

function loadRuntime(): Runtime {
  try {
    const config = getTelemetryRuntimeConfig();
    if (config.mode === "demo") {
      return { mode: "demo", apiBaseUrl: null, configuredOrganizationId: null, error: null };
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

export function useDashboardSecurity(): DashboardSecurityModel {
  const [runtime] = useState<Runtime>(loadRuntime);
  const [state, setState] = useState<DashboardSecurityState>(() =>
    runtime.mode === "demo" ? "demo" : runtime.error ? "error" : "loading",
  );
  const [session, setSession] = useState<SecuritySession | null>(null);
  const [membership, setMembership] = useState<SecurityMembership | null>(null);
  const [error, setError] = useState<string | null>(runtime.error);
  const [generation, setGeneration] = useState(0);

  const retry = useCallback(() => {
    if (runtime.mode === "demo") return;
    if (!runtime.apiBaseUrl) {
      setState("error");
      setError(runtime.error ?? "Authenticated dashboard API is unavailable.");
      return;
    }
    setState("loading");
    setError(null);
    setGeneration((value) => value + 1);
  }, [runtime]);

  useEffect(() => {
    if (runtime.mode === "demo" || !runtime.apiBaseUrl) return;

    let cancelled = false;
    const credentialProvider = createRuntimeCredentialProvider(runtime.configuredOrganizationId);
    const authenticatedFetch = createAuthenticatedFetch(fetch.bind(globalThis), credentialProvider);
    const client = new HttpSecuritySessionClient({
      apiBaseUrl: runtime.apiBaseUrl,
      fetchImpl: authenticatedFetch,
    });

    void client.getSession().then(async (result) => {
      if (cancelled) return;
      if (!result.ok) {
        setSession(null);
        setMembership(null);
        setError(result.error.message);
        setState(
          result.error.code === "AUTHENTICATION_REQUIRED"
            ? "unauthenticated"
            : result.error.code === "ACCESS_DENIED"
              ? "forbidden"
              : "error",
        );
        return;
      }

      const selected = chooseMembership(result.value, runtime.configuredOrganizationId);
      if (!selected) {
        setSession(result.value);
        setMembership(null);
        setError("Вибрана організація відсутня у перевіреній сесії користувача.");
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
      setSession(result.value);
      setMembership(selected);
      setError(null);
      setState("ready");
    });

    return () => {
      cancelled = true;
    };
  }, [generation, runtime]);

  const selectOrganization = useCallback(
    (organizationId: string) => {
      if (!session) return;
      const selected = session.memberships.find((item) => item.organizationId === organizationId);
      if (!selected) {
        setError("Вибрана організація відсутня у перевіреній сесії користувача.");
        setState("forbidden");
        return;
      }
      const credentials = getSecurityCredentials();
      setSecurityCredentials({
        accessToken: credentials.accessToken,
        organizationId: selected.organizationId,
      });
      persistOrganizationId(selected.organizationId);
      setMembership(selected);
      setError(null);
      setState("ready");
    },
    [session],
  );

  const signOut = useCallback(async () => {
    await signOutSupabase();
    clearPersistedOrganizationId();
    setSecurityCredentials({ accessToken: null, organizationId: null });
    setSession(null);
    setMembership(null);
    setError(null);
    setState(runtime.mode === "demo" ? "demo" : "unauthenticated");
  }, [runtime.mode]);

  return useMemo(
    () => ({
      mode: runtime.mode,
      state,
      session,
      membership,
      error,
      selectOrganization,
      retry,
      signOut,
    }),
    [error, membership, retry, runtime.mode, selectOrganization, session, signOut, state],
  );
}
