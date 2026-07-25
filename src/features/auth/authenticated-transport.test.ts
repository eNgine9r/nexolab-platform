import { describe, expect, it, vi } from "vitest";

import { createAuthenticatedFetch } from "./authenticated-transport";

describe("authenticated transport", () => {
  it("injects the latest bearer token without overriding an explicit header", async () => {
    let token = "token-1";
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 204 }));
    const authenticatedFetch = createAuthenticatedFetch(() => token, fetchImpl);

    await authenticatedFetch("https://api.example.test/first");
    token = "token-2";
    await authenticatedFetch("https://api.example.test/second", {
      headers: { Authorization: "Bearer explicit" },
    });

    const firstHeaders = fetchImpl.mock.calls[0]?.[1]?.headers as Headers;
    const secondHeaders = fetchImpl.mock.calls[1]?.[1]?.headers as Headers;
    expect(firstHeaders.get("Authorization")).toBe("Bearer token-1");
    expect(secondHeaders.get("Authorization")).toBe("Bearer explicit");
  });

  it("leaves anonymous requests without an Authorization header", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 204 }));
    const authenticatedFetch = createAuthenticatedFetch(() => null, fetchImpl);

    await authenticatedFetch("https://api.example.test/health");

    const headers = fetchImpl.mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.has("Authorization")).toBe(false);
  });
});
