import { createClient, type SupabaseClient } from "@supabase/supabase-js";

import { createLocalCredentialProvider } from "./local-auth";
import {
  getSecurityCredentials,
  setSecurityCredentials,
  type SecurityCredentialProvider,
  type SecurityCredentialSnapshot,
} from "./security-session";

const ACCEPTANCE_TOKEN_KEY = "nexolab.acceptance.access-token";
const ACCEPTANCE_ORGANIZATION_KEY = "nexolab.acceptance.organization-id";

let client: SupabaseClient | null | undefined;
const runtimeCredentialProviders = new Map<string, SecurityCredentialProvider>();

export type SupabaseAuthResult = { ok: true } | { ok: false; message: string };

export function getSupabaseAuthClient(): SupabaseClient | null {
  if (client !== undefined) return client;
  if (typeof window === "undefined") {
    client = null;
    return client;
  }

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL?.trim();
  const publishableKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY?.trim();
  if (!url || !publishableKey) {
    client = null;
    return client;
  }

  client = createClient(url, publishableKey, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
    },
  });
  client.auth.onAuthStateChange((_event, session) => {
    const current = getSecurityCredentials();
    setSecurityCredentials({
      accessToken: session?.access_token ?? null,
      organizationId: current.organizationId,
    });
  });
  return client;
}

/**
 * Compatibility entry point for production clients that predate auth-runtime.ts.
 * Local authentication must still rotate through the local refresh-token provider;
 * never fall back to a stale in-memory bearer token.
 */
export function createRuntimeCredentialProvider(organizationId: string | null): SecurityCredentialProvider {
  const resolvedOrganizationId =
    organizationId ?? process.env.NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID?.trim() ?? null;
  const providerKind = (process.env.NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER ?? "supabase").trim().toLowerCase();
  const localApiBaseUrl = process.env.NEXT_PUBLIC_NEXOLAB_API_BASE_URL?.trim() ?? "";
  const providerScope = providerKind === "local" ? localApiBaseUrl : "";
  const cacheKey = `${providerKind}:${providerScope}:${resolvedOrganizationId ?? "__default_organization__"}`;
  const cached = runtimeCredentialProviders.get(cacheKey);
  if (cached) return cached;

  let provider: SecurityCredentialProvider;
  if (providerKind === "acceptance") {
    provider = async (): Promise<SecurityCredentialSnapshot> => {
      if (typeof window === "undefined") {
        return { accessToken: null, organizationId: resolvedOrganizationId };
      }
      const snapshot = {
        accessToken: window.sessionStorage.getItem(ACCEPTANCE_TOKEN_KEY),
        organizationId:
          window.sessionStorage.getItem(ACCEPTANCE_ORGANIZATION_KEY) ?? resolvedOrganizationId,
      };
      setSecurityCredentials(snapshot);
      return snapshot;
    };
  } else if (providerKind === "local") {
    provider = localApiBaseUrl
      ? createLocalCredentialProvider(localApiBaseUrl, resolvedOrganizationId)
      : async (): Promise<SecurityCredentialSnapshot> => {
          const snapshot = { accessToken: null, organizationId: resolvedOrganizationId };
          setSecurityCredentials(snapshot);
          return snapshot;
        };
  } else {
    provider = createSupabaseCredentialProvider(resolvedOrganizationId);
  }

  runtimeCredentialProviders.set(cacheKey, provider);
  return provider;
}

export function createSupabaseCredentialProvider(organizationId: string | null): SecurityCredentialProvider {
  return async (): Promise<SecurityCredentialSnapshot> => {
    const current = getSecurityCredentials();
    const supabase = getSupabaseAuthClient();
    if (!supabase) {
      return {
        accessToken: current.accessToken,
        organizationId: current.organizationId ?? organizationId,
      };
    }

    const { data, error } = await supabase.auth.getSession();
    if (error) {
      return {
        accessToken: null,
        organizationId: current.organizationId ?? organizationId,
      };
    }
    const snapshot = {
      accessToken: data.session?.access_token ?? null,
      organizationId: current.organizationId ?? organizationId,
    };
    setSecurityCredentials(snapshot);
    return snapshot;
  };
}

export async function signInWithPassword(email: string, password: string): Promise<SupabaseAuthResult> {
  const supabase = getSupabaseAuthClient();
  if (!supabase) {
    return {
      ok: false,
      message: "Supabase Auth не налаштовано для цього середовища.",
    };
  }

  const { data, error } = await supabase.auth.signInWithPassword({
    email: email.trim(),
    password,
  });
  if (error || !data.session) {
    return {
      ok: false,
      message: error?.message ?? "Сесію користувача не створено.",
    };
  }
  const current = getSecurityCredentials();
  setSecurityCredentials({
    accessToken: data.session.access_token,
    organizationId: current.organizationId,
  });
  return { ok: true };
}

export async function signOut(): Promise<void> {
  const supabase = getSupabaseAuthClient();
  if (supabase) {
    await supabase.auth.signOut();
  }
  if (typeof window !== "undefined") {
    window.sessionStorage.removeItem(ACCEPTANCE_TOKEN_KEY);
    window.sessionStorage.removeItem(ACCEPTANCE_ORGANIZATION_KEY);
  }
  setSecurityCredentials({ accessToken: null, organizationId: null });
}
