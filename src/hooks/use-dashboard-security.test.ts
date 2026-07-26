import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getSecurityCredentials, setSecurityCredentials } from "@/features/security/security-session";

const authState = vi.hoisted(() => ({
  signOut: vi.fn(),
  credentials: vi.fn(),
}));

vi.mock("@/lib/telemetry/runtime-config", () => ({
  getTelemetryRuntimeConfig: () => ({
    mode: "live",
    apiBaseUrl: "https://api.example.test",
    websocketUrl: "wss://api.example.test/api/v1/telemetry/live",
  }),
}));

vi.mock("@/features/security/supabase-auth", () => ({
  createRuntimeCredentialProvider: () => authState.credentials,
  signOut: authState.signOut,
}));

import { useDashboardSecurity } from "./use-dashboard-security";

const sessionPayload = {
  authenticated: true,
  identity: {
    id: "identity-1",
    provider: "test-oidc",
    subject: "engineer-user",
    email: "engineer@example.test",
    display_name: "Engineer User",
  },
  memberships: [
    {
      organization_id: "org-1",
      organization_slug: "lab-one",
      organization_name: "Laboratory One",
      roles: ["engineer"],
      permissions: ["dashboard.read", "telemetry.read", "sessions.manage"],
    },
    {
      organization_id: "org-2",
      organization_slug: "lab-two",
      organization_name: "Laboratory Two",
      roles: ["viewer"],
      permissions: ["dashboard.read", "telemetry.read"],
    },
  ],
};

describe("useDashboardSecurity", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    window.sessionStorage.clear();
    setSecurityCredentials({ accessToken: null, organizationId: null });
    authState.credentials.mockResolvedValue({
      accessToken: "access-token",
      organizationId: null,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify(sessionPayload), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
      ),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads the verified session and switches only between returned memberships", async () => {
    window.localStorage.setItem("nexolab.selectedOrganizationId", "org-2");
    const { result } = renderHook(() => useDashboardSecurity());

    await waitFor(() => {
      expect(result.current.state).toBe("ready");
    });
    expect(result.current.membership?.organizationId).toBe("org-2");
    expect(getSecurityCredentials()).toEqual({
      accessToken: "access-token",
      organizationId: "org-2",
    });

    act(() => {
      result.current.selectOrganization("org-1");
    });
    expect(result.current.membership?.organizationId).toBe("org-1");
    expect(getSecurityCredentials().organizationId).toBe("org-1");

    act(() => {
      result.current.selectOrganization("foreign-org");
    });
    expect(result.current.state).toBe("forbidden");
    expect(result.current.error).toContain("відсутня");
  });

  it("rejects an explicitly selected organization that is not in the verified session", async () => {
    setSecurityCredentials({ accessToken: "access-token", organizationId: "foreign-org" });
    authState.credentials.mockResolvedValue({
      accessToken: "access-token",
      organizationId: "foreign-org",
    });

    const { result } = renderHook(() => useDashboardSecurity());

    await waitFor(() => {
      expect(result.current.state).toBe("forbidden");
    });
    expect(result.current.membership).toBeNull();
    expect(result.current.error).toContain("відсутня");
  });

  it("clears credentials and persisted organization on logout", async () => {
    window.localStorage.setItem("nexolab.selectedOrganizationId", "org-1");
    const { result } = renderHook(() => useDashboardSecurity());
    await waitFor(() => expect(result.current.state).toBe("ready"));

    await act(async () => {
      await result.current.signOut();
    });

    expect(authState.signOut).toHaveBeenCalledOnce();
    expect(result.current.state).toBe("unauthenticated");
    expect(window.localStorage.getItem("nexolab.selectedOrganizationId")).toBeNull();
    expect(getSecurityCredentials()).toEqual({
      accessToken: null,
      organizationId: null,
    });
  });
});
