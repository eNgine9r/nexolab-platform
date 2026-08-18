import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.sessionStorage.clear();
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

  it("rotates an expired local bearer through the legacy runtime credential entry point", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-18T07:30:00Z"));
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER", "local");
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_API_BASE_URL", "http://127.0.0.1:8082");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "not-a-valid-url");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "invalid-key");

    const createClient = vi.fn(() => {
      throw new Error("Supabase must not initialize for local authentication");
    });
    vi.doMock("@supabase/supabase-js", () => ({ createClient }));

    const tokenResponse = (accessToken: string, refreshToken: string, expiresIn: number) =>
      new Response(
        JSON.stringify({
          token_type: "Bearer",
          access_token: accessToken,
          refresh_token: refreshToken,
          expires_in: expiresIn,
          refresh_expires_in: 3600,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(tokenResponse("access-1", "refresh-1", 1))
      .mockResolvedValueOnce(tokenResponse("access-2", "refresh-2", 300));
    vi.stubGlobal("fetch", fetchMock);

    const { signInWithLocalPassword } = await import("./local-auth");
    const { createRuntimeCredentialProvider } = await import("./supabase-auth");

    await expect(
      signInWithLocalPassword("http://127.0.0.1:8082", "operator", "valid-password"),
    ).resolves.toEqual({ ok: true });
    await vi.advanceTimersByTimeAsync(2_000);

    const credentials = await createRuntimeCredentialProvider("11111111-1111-1111-1111-111111111111")();

    expect(credentials).toEqual({
      accessToken: "access-2",
      organizationId: "11111111-1111-1111-1111-111111111111",
    });
    expect(createClient).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1]?.[0]).toBe("http://127.0.0.1:8082/api/v1/auth/local/refresh");
    expect(window.sessionStorage.getItem("nexolab.local-auth.refresh-token")).toBe("refresh-2");
  });

  it("fails closed instead of reusing a stale local bearer when the API URL is missing", async () => {
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER", "local");
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_API_BASE_URL", "");
    const createClient = vi.fn();
    vi.doMock("@supabase/supabase-js", () => ({ createClient }));

    const { setSecurityCredentials } = await import("./security-session");
    setSecurityCredentials({
      accessToken: "stale-local-access",
      organizationId: "11111111-1111-1111-1111-111111111111",
    });
    const { createRuntimeCredentialProvider } = await import("./supabase-auth");

    await expect(
      createRuntimeCredentialProvider("11111111-1111-1111-1111-111111111111")(),
    ).resolves.toEqual({
      accessToken: null,
      organizationId: "11111111-1111-1111-1111-111111111111",
    });
    expect(createClient).not.toHaveBeenCalled();
  });
});
