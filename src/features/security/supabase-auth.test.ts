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
            subject: "subject-1",
            session_id: "session-1",
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

it.each([false, true])(
  "preserves a newly selected organization during an async Supabase read (error=%s)",
  async (error) => {
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER", "supabase");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "test-key");
    let resolve!: (value: unknown) => void;
    const getSession = vi.fn(
      () =>
        new Promise((finish) => {
          resolve = finish;
        }),
    );
    vi.doMock("@supabase/supabase-js", () => ({
      createClient: () => ({ auth: { onAuthStateChange: vi.fn(), getSession } }),
    }));
    const { getSecurityCredentials, setSecurityCredentials } = await import("./security-session");
    const { createSupabaseCredentialProvider } = await import("./supabase-auth");
    setSecurityCredentials({ accessToken: "old-token", organizationId: "org-a" });
    const pending = createSupabaseCredentialProvider("org-a")();
    setSecurityCredentials({ accessToken: "old-token", organizationId: "org-b" });
    resolve({
      data: { session: error ? null : { access_token: "fresh-token" } },
      error: error ? new Error("read failed") : null,
    });
    expect((await pending).organizationId).toBe("org-b");
    expect(getSecurityCredentials().organizationId).toBe("org-b");
  },
);
it("does not restore credentials returned by a Supabase read after logout", async () => {
  vi.stubEnv("NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER", "supabase");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "test-key");
  let resolve!: (value: unknown) => void;
  vi.doMock("@supabase/supabase-js", () => ({
    createClient: () => ({
      auth: {
        onAuthStateChange: vi.fn(),
        getSession: () =>
          new Promise((finish) => {
            resolve = finish;
          }),
      },
    }),
  }));
  const { getSecurityCredentials, setSecurityCredentials } = await import("./security-session");
  const { createSupabaseCredentialProvider } = await import("./supabase-auth");
  setSecurityCredentials({ accessToken: "old-token", organizationId: "org-a" });
  const pending = createSupabaseCredentialProvider("org-a")();
  setSecurityCredentials({ accessToken: null, organizationId: null });
  resolve({ data: { session: { access_token: "stale-token" } }, error: null });
  expect(await pending).toEqual({ accessToken: null, organizationId: null });
  expect(getSecurityCredentials()).toEqual({ accessToken: null, organizationId: null });
});
