import { describe, expect, it, vi } from "vitest";

import { LocalUserAdminApiError, LocalUserAdminClient } from "./local-user-admin";

const API_BASE_URL = "http://127.0.0.1:8082";

function createClient(
  fetchImpl: typeof fetch,
  accessToken: string | null = "test-token",
): LocalUserAdminClient {
  return new LocalUserAdminClient({
    apiBaseUrl: API_BASE_URL,
    fetchImpl,
    credentials: () => ({ accessToken, organizationId: "test-organization" }),
  });
}

describe("LocalUserAdminClient", () => {
  it("keeps the create payload in the browser when current credentials have no bearer token", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const client = createClient(fetchImpl, null);

    await expect(
      client.createUser({
        username: "fixture-operator",
        password: "fixture-password",
        role: "laboratory_technician",
        permissions: [],
      }),
    ).rejects.toMatchObject({
      status: 401,
      code: "local_user_admin_authentication_required",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("classifies an unmounted admin route as a LOCAL_LAN profile mismatch", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: "Not Found" }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
    ) as unknown as typeof fetch;
    const client = createClient(fetchImpl);

    await expect(client.listUsers()).rejects.toMatchObject({
      name: "LocalUserAdminApiError",
      status: 404,
      code: "local_user_admin_route_unavailable",
    });

    try {
      await client.listUsers();
    } catch (cause) {
      expect(cause).toBeInstanceOf(LocalUserAdminApiError);
      expect((cause as Error).message).toContain("LOCAL_LAN");
      expect((cause as Error).message).toContain("local-auth");
    }
  });

  it("preserves a structured backend 404 instead of rewriting it as a profile mismatch", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            detail: {
              code: "local_user_not_found",
              message: "Користувача не знайдено.",
            },
          }),
          {
            status: 404,
            headers: { "Content-Type": "application/json" },
          },
        ),
    ) as unknown as typeof fetch;
    const client = createClient(fetchImpl);

    await expect(client.updateUser("missing-user", { isActive: false })).rejects.toMatchObject({
      status: 404,
      code: "local_user_not_found",
      message: "Користувача не знайдено.",
    });
  });
});
