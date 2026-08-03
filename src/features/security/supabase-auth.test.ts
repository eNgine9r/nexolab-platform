import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("optional Supabase authentication", () => {
  it("does not initialize Supabase or perform a request when configuration is absent", async () => {
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const createClient = vi.fn();
    vi.doMock("@supabase/supabase-js", () => ({ createClient }));

    const { getSupabaseAuthClient, signInWithPassword } = await import("./supabase-auth");

    expect(getSupabaseAuthClient()).toBeNull();
    await expect(signInWithPassword("operator@example.invalid", "password")).resolves.toEqual({
      ok: false,
      message: "Supabase Auth не налаштовано для цього середовища.",
    });
    expect(createClient).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("keeps local authentication primary even when Supabase configuration is invalid", async () => {
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER", "local");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "not-a-valid-url");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "invalid-key");
    const createClient = vi.fn(() => {
      throw new Error("Supabase must not initialize for local authentication");
    });
    vi.doMock("@supabase/supabase-js", () => ({ createClient }));
    const fetchMock = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            token_type: "Bearer",
            access_token: "local-access",
            refresh_token: "local-refresh",
            expires_in: 300,
            refresh_expires_in: 3600,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { runtimeAuthProvider, signInWithPassword } = await import("./auth-runtime");

    expect(runtimeAuthProvider()).toBe("local");
    await expect(signInWithPassword("http://127.0.0.1:8082", "operator", "valid-password")).resolves.toEqual({
      ok: true,
    });
    expect(createClient).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8082/api/v1/auth/local/login",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
