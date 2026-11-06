import { describe, expect, it, vi } from "vitest";

import { LocalUserAdminApiError, LocalUserAdminClient } from "./local-user-admin";

const API_BASE_URL = "http://127.0.0.1:8082";

function createClient(fetchImpl: typeof fetch): LocalUserAdminClient {
  return new LocalUserAdminClient({ apiBaseUrl: API_BASE_URL, fetchImpl });
}

describe("LocalUserAdminClient", () => {
  it("exposes named navigation grants without inferring resource permissions", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            items: [
              { value: "navigation.reports", grantable: true, administrator_only: false },
              { value: "reports.read", grantable: true, administrator_only: false },
            ],
          }),
        ),
    ) as unknown as typeof fetch;
    const options = await createClient(fetchImpl).permissions();
    expect(options).toEqual([
      { value: "navigation.reports", grantable: true, administratorOnly: false },
      { value: "reports.read", grantable: true, administratorOnly: false },
    ]);
  });

  it("declares navigation-aware permission replacement", async () => {
    const calls: RequestInit[] = [];
    const fetchImpl = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      if (init) calls.push(init);
      return new Response(
        JSON.stringify({
          id: "account-1",
          identity_id: "identity-1",
          username: "operator",
          is_active: true,
          role: "engineer",
          legacy_roles: [],
          granted_permissions: ["navigation.reports"],
          effective_permissions: ["navigation.reports"],
          created_at: "2026-01-01T00:00:00Z",
          password_changed_at: "2026-01-01T00:00:00Z",
          last_authenticated_at: "2026-01-01T00:00:00Z",
        }),
      );
    }) as unknown as typeof fetch;
    const result = await createClient(fetchImpl).setPermissions("account-1", ["navigation.reports"]);
    expect(result.grantedPermissions).toEqual(["navigation.reports"]);
    expect(JSON.parse(String(calls[0]?.body))).toMatchObject({
      permissions: ["navigation.reports"],
      navigation_contract_version: 1,
    });
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
