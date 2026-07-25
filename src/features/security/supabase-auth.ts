import { createClient, type SupabaseClient } from "@supabase/supabase-js";

import {
  getSecurityCredentials,
  setSecurityCredentials,
  type SecurityCredentialProvider,
  type SecurityCredentialSnapshot,
} from "./security-session";

const ACCEPTANCE_TOKEN_KEY = "nexolab.acceptance.access-token";
const ACCEPTANCE_ORGANIZATION_KEY = "nexolab.acceptance.organization-id";

let client: SupabaseClient | null | undefined;

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

export function createRuntimeCredentialProvider(organizationId: string | null): SecurityCredentialProvider {
  if (process.env.NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER === "acceptance") {
    return async (): Promise<SecurityCredentialSnapshot> => {
      if (typeof window === "undefined") {
        return { accessToken: null, organizationId };
      }
      const snapshot = {
        accessToken: window.sessionStorage.getItem(ACCEPTANCE_TOKEN_KEY),
        organizationId: window.sessionStorage.getItem(ACCEPTANCE_ORGANIZATION_KEY) ?? organizationId,
      };
      setSecurityCredentials(snapshot);
      return snapshot;
    };
  }
  return createSupabaseCredentialProvider(organizationId);
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
  setSecurityCredentials({ accessToken: null, organizationId: null });
}
