import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getSecurityCredentials, setSecurityCredentials } from "@/features/security/security-session";

import { createSessionApiClient, type SessionFetch } from "./api-client";

const emptyPage = {
  items: [],
  count: 0,
  limit: 100,
  offset: 0,
  next_offset: null,
};

function createFetchMock() {
  return vi.fn<SessionFetch>(async (input, init) => {
    void input;
    void init;
    return new Response(JSON.stringify(emptyPage), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
}

describe("authenticated Session API client", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_DATA_MODE", "live");
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_API_BASE_URL", "https://api.example.test");
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID", "configured-org");
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER", "supabase");
    setSecurityCredentials({
      accessToken: "verified-access-token",
      organizationId: "selected-org",
    });
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    setSecurityCredentials({ accessToken: null, organizationId: null });
  });

  it("adds the verified bearer token and selected organization to session reads", async () => {
    const fetchImpl = createFetchMock();
    const client = createSessionApiClient({ fetch: fetchImpl });

    await client.listSessions();

    expect(fetchImpl).toHaveBeenCalledOnce();
    const firstCall = fetchImpl.mock.calls[0];
    expect(firstCall).toBeDefined();
    const [url, init] = firstCall!;
    const headers = new Headers(init?.headers);
    expect(url).toBe("https://api.example.test/api/v1/sessions?limit=100&offset=0");
    expect(headers.get("Authorization")).toBe("Bearer verified-access-token");
    expect(headers.get("X-Organization-ID")).toBe("selected-org");
  });

  it("refreshes credentials for each request instead of freezing the first organization", async () => {
    const fetchImpl = createFetchMock();
    const client = createSessionApiClient({ fetch: fetchImpl });

    await client.listSessions();
    setSecurityCredentials({
      accessToken: "refreshed-access-token",
      organizationId: "second-org",
    });
    await client.listSessions();

    const secondCall = fetchImpl.mock.calls[1];
    expect(secondCall).toBeDefined();
    const secondHeaders = new Headers(secondCall![1]?.headers);
    expect(secondHeaders.get("Authorization")).toBe("Bearer refreshed-access-token");
    expect(secondHeaders.get("X-Organization-ID")).toBe("second-org");
  });
});

describe("explicit verified organization scope", () => {
  it("does not overwrite a selected organization with acceptance defaults", async () => {
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_DATA_MODE", "live");
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_API_BASE_URL", "https://api.example.test");
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER", "acceptance");
    window.sessionStorage.setItem("nexolab.acceptance.access-token", "old-token");
    window.sessionStorage.setItem("nexolab.acceptance.organization-id", "old-org");
    setSecurityCredentials({ accessToken: "verified-token", organizationId: "org-b" });
    const fetchImpl = createFetchMock();
    const client = createSessionApiClient({ fetch: fetchImpl, organizationId: "org-b" });
    try {
      await client.listSessions();
      const requestHeaders = new Headers(fetchImpl.mock.calls[0]![1]?.headers);
      expect(requestHeaders.get("X-Organization-ID")).toBe("org-b");
      expect(requestHeaders.get("Authorization")).toBe("Bearer verified-token");
      expect(getSecurityCredentials().organizationId).toBe("org-b");
      setSecurityCredentials({ accessToken: "refreshed-token", organizationId: "org-b" });
      await client.listSessions();
      expect(new Headers(fetchImpl.mock.calls[1]![1]?.headers).get("Authorization")).toBe(
        "Bearer refreshed-token",
      );
    } finally {
      window.sessionStorage.clear();
      vi.unstubAllEnvs();
      setSecurityCredentials({ accessToken: null, organizationId: null });
    }
  });
});

it("refreshes an expired local token while retaining the explicit organization", async () => {
  vi.stubEnv("NEXT_PUBLIC_NEXOLAB_DATA_MODE", "live");
  vi.stubEnv("NEXT_PUBLIC_NEXOLAB_API_BASE_URL", "https://api.example.test");
  vi.stubEnv("NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER", "local");
  window.sessionStorage.setItem("nexolab.local-auth.access-token", "expired-token");
  window.sessionStorage.setItem("nexolab.local-auth.refresh-token", "refresh-token");
  window.sessionStorage.setItem("nexolab.local-auth.access-expires-at", "0");
  setSecurityCredentials({ accessToken: "expired-token", organizationId: "org-b" });
  const refresh = vi.fn(
    async () =>
      new Response(
        JSON.stringify({
          access_token: "fresh-token",
          refresh_token: "new-refresh-token",
          expires_in: 600,
          refresh_expires_in: 3600,
        }),
        { status: 200 },
      ),
  );
  vi.stubGlobal("fetch", refresh);
  try {
    const fetchImpl = createFetchMock();
    await createSessionApiClient({ fetch: fetchImpl, organizationId: "org-b" }).listSessions();
    expect(refresh).toHaveBeenCalledWith(
      "https://api.example.test/api/v1/auth/local/refresh",
      expect.objectContaining({ method: "POST" }),
    );
    const headers = new Headers(fetchImpl.mock.calls[0]![1]?.headers);
    expect(headers.get("Authorization")).toBe("Bearer fresh-token");
    expect(headers.get("X-Organization-ID")).toBe("org-b");
  } finally {
    window.sessionStorage.clear();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    setSecurityCredentials({ accessToken: null, organizationId: null });
  }
});

it("pins an old scoped request without reverting the UI organization during delayed local refresh", async () => {
  vi.stubEnv("NEXT_PUBLIC_NEXOLAB_DATA_MODE", "live");
  vi.stubEnv("NEXT_PUBLIC_NEXOLAB_API_BASE_URL", "https://api.example.test");
  vi.stubEnv("NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER", "local");
  window.sessionStorage.setItem("nexolab.local-auth.access-token", "expired");
  window.sessionStorage.setItem("nexolab.local-auth.refresh-token", "refresh-old");
  window.sessionStorage.setItem("nexolab.local-auth.access-expires-at", "0");
  setSecurityCredentials({ accessToken: "expired", organizationId: "org-a" });
  let resolve!: (response: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn(
      () =>
        new Promise<Response>((finish) => {
          resolve = finish;
        }),
    ),
  );
  try {
    const oldFetch = createFetchMock();
    const pending = createSessionApiClient({ fetch: oldFetch, organizationId: "org-a" }).listSessions();
    await vi.waitFor(() => expect(resolve).toBeDefined());
    setSecurityCredentials({ accessToken: "expired", organizationId: "org-b" });
    resolve(
      new Response(
        JSON.stringify({
          access_token: "fresh",
          refresh_token: "refresh-new",
          expires_in: 600,
          refresh_expires_in: 3600,
        }),
        { status: 200 },
      ),
    );
    await pending;
    expect(new Headers(oldFetch.mock.calls[0]![1]?.headers).get("X-Organization-ID")).toBe("org-a");
    expect(getSecurityCredentials().organizationId).toBe("org-b");
    const nextFetch = createFetchMock();
    await createSessionApiClient({ fetch: nextFetch }).listSessions();
    expect(new Headers(nextFetch.mock.calls[0]![1]?.headers).get("X-Organization-ID")).toBe("org-b");
  } finally {
    window.sessionStorage.clear();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    setSecurityCredentials({ accessToken: null, organizationId: null });
  }
});
