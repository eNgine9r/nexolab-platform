import type { SecurityCredentialProvider } from "./security-session";
import {
  createRuntimeCredentialProvider as createSupabaseCredentialProvider,
  signInWithPassword as signInWithSupabasePassword,
  signOut as signOutSupabase,
  type SupabaseAuthResult,
} from "./supabase-auth";
import {
  createLocalCredentialProvider,
  signInWithLocalPassword,
  signOutLocal,
  type LocalAuthResult,
} from "./local-auth";

export type RuntimeAuthResult = SupabaseAuthResult | LocalAuthResult;

export function runtimeAuthProvider(): string {
  return process.env.NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER?.trim().toLowerCase() || "disabled";
}

export function createRuntimeCredentialProvider(
  apiBaseUrl: string,
  organizationId: string | null,
): SecurityCredentialProvider {
  if (runtimeAuthProvider() === "local") {
    return createLocalCredentialProvider(apiBaseUrl, organizationId);
  }
  return createSupabaseCredentialProvider(organizationId);
}

export async function signInWithPassword(
  apiBaseUrl: string | null,
  usernameOrEmail: string,
  password: string,
): Promise<RuntimeAuthResult> {
  if (runtimeAuthProvider() === "local") {
    if (!apiBaseUrl) {
      return {
        ok: false,
        message: "NEXOLAB API не налаштовано для локальної автентифікації.",
      };
    }
    return signInWithLocalPassword(apiBaseUrl, usernameOrEmail, password);
  }
  return signInWithSupabasePassword(usernameOrEmail, password);
}

export async function signOut(apiBaseUrl: string | null): Promise<void> {
  if (runtimeAuthProvider() === "local") {
    if (apiBaseUrl) {
      await signOutLocal(apiBaseUrl);
    }
    return;
  }
  await signOutSupabase();
}
