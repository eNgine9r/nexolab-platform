import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setSecurityCredentials } from "@/features/security/security-session";

import { createSessionApiClient } from "./api-client";

const emptyPage = {
  items: [],
  count: 0,
  limit: 100,
  offset: 0,
  next_offset: null,
};

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
    const fetchImpl = vi.fn(
      async () =>
        new Response(JSON.stringify(emptyPage), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    );
    const client = createSessionApiClient({ fetch: fetchImpl });

    await client.listSessions();

    expect(fetchImpl).toHaveBeenCalledOnce();
    const [url, init] = fetchImpl.mock.calls[0];
    const headers = new Headers(init?.headers);
    expect(url).toBe("https://api.example.test/api/v1/sessions?limit=100&offset=0");
    expect(headers.get("Authorization")).toBe("Bearer verified-access-token");
    expect(headers.get("X-Organization-ID")).toBe("selected-org");
  });

  it("refreshes credentials for each request instead of freezing the first organization", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(JSON.stringify(emptyPage), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    );
    const client = createSessionApiClient({ fetch: fetchImpl });

    await client.listSessions();
    setSecurityCredentials({
      accessToken: "refreshed-access-token",
      organizationId: "second-org",
    });
    await client.listSessions();

    const secondHeaders = new Headers(fetchImpl.mock.calls[1][1]?.headers);
    expect(secondHeaders.get("Authorization")).toBe("Bearer refreshed-access-token");
    expect(secondHeaders.get("X-Organization-ID")).toBe("second-org");
  });
});
