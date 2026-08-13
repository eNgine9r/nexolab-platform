import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as refrigerationCache from "@/features/refrigeration/refrigeration-structural-cache";
import { getSecurityCredentials, setSecurityCredentials } from "@/features/security/security-session";
import * as readModelCache from "@/lib/monitoring-read-model-cache";

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

function sessionResponse(): Response {
  return new Response(JSON.stringify(sessionPayload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("useDashboardSecurity", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    readModelCache.clearAllMonitoringReadModels();
    refrigerationCache.clearAllRefrigerationStructuralCaches();
    window.localStorage.clear();
    window.sessionStorage.clear();
    setSecurityCredentials({ accessToken: null, organizationId: null });
    authState.credentials.mockResolvedValue({
      accessToken: "access-token",
      organizationId: null,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => sessionResponse()),
    );
  });

  afterEach(() => {
    readModelCache.clearAllMonitoringReadModels();
    refrigerationCache.clearAllRefrigerationStructuralCaches();
    vi.unstubAllGlobals();
  });

  it("deduplicates the verified session across rapid route consumers", async () => {
    const fetchMock = vi.fn(async () => sessionResponse());
    vi.stubGlobal("fetch", fetchMock);

    const first = renderHook(() => useDashboardSecurity());
    const second = renderHook(() => useDashboardSecurity());

    await waitFor(() => {
      expect(first.result.current.state).toBe("ready");
      expect(second.result.current.state).toBe("ready");
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    first.unmount();
    second.unmount();
  });

  it("loads the verified session and switches only between returned memberships", async () => {
    window.localStorage.setItem("nexolab.selectedOrganizationId", "org-2");
    const clearReadModels = vi.spyOn(readModelCache, "clearAllMonitoringReadModels");
    const clearRefrigeration = vi.spyOn(refrigerationCache, "clearAllRefrigerationStructuralCaches");
    const { result } = renderHook(() => useDashboardSecurity());

    await waitFor(() => {
      expect(result.current.state).toBe("ready");
    });
    expect(result.current.membership?.organizationId).toBe("org-2");
    expect(result.current.errorCode).toBeNull();
    expect(result.current.diagnostics).toBeNull();
    expect(getSecurityCredentials()).toEqual({
      accessToken: "access-token",
      organizationId: "org-2",
    });

    act(() => {
      result.current.selectOrganization("org-1");
    });
    expect(result.current.membership?.organizationId).toBe("org-1");
    expect(getSecurityCredentials().organizationId).toBe("org-1");
    expect(clearReadModels).toHaveBeenCalledTimes(1);
    expect(clearRefrigeration).toHaveBeenCalledTimes(1);

    act(() => {
      result.current.selectOrganization("foreign-org");
    });
    expect(result.current.state).toBe("forbidden");
    expect(result.current.errorCode).toBe("ORGANIZATION_NOT_AVAILABLE");
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
    expect(result.current.errorCode).toBe("ORGANIZATION_NOT_AVAILABLE");
    expect(result.current.error).toContain("відсутня");
  });

  it("retries with a fresh request after a browser transport failure", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(sessionResponse());
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useDashboardSecurity());

    await waitFor(() => {
      expect(result.current.state).toBe("error");
    });
    expect(result.current.errorCode).toBe("SESSION_API_UNREACHABLE_OR_ORIGIN_BLOCKED");
    expect(result.current.diagnostics).toMatchObject({
      apiOrigin: "https://api.example.test",
      browserOrigin: window.location.origin,
      endpointPath: "/api/v1/auth/session",
    });

    act(() => {
      result.current.retry();
    });

    expect(result.current.state).toBe("loading");
    expect(result.current.errorCode).toBeNull();
    expect(result.current.diagnostics).toBeNull();
    await waitFor(() => {
      expect(result.current.state).toBe("ready");
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("clears credentials, persisted organization and retained read models on logout", async () => {
    window.localStorage.setItem("nexolab.selectedOrganizationId", "org-1");
    const clearReadModels = vi.spyOn(readModelCache, "clearAllMonitoringReadModels");
    const clearRefrigeration = vi.spyOn(refrigerationCache, "clearAllRefrigerationStructuralCaches");
    const { result } = renderHook(() => useDashboardSecurity());
    await waitFor(() => expect(result.current.state).toBe("ready"));

    clearReadModels.mockClear();
    clearRefrigeration.mockClear();
    await act(async () => {
      await result.current.signOut();
    });

    expect(authState.signOut).toHaveBeenCalledOnce();
    expect(clearReadModels).toHaveBeenCalledTimes(1);
    expect(clearRefrigeration).toHaveBeenCalledTimes(1);
    expect(result.current.state).toBe("unauthenticated");
    expect(result.current.errorCode).toBeNull();
    expect(window.localStorage.getItem("nexolab.selectedOrganizationId")).toBeNull();
    expect(getSecurityCredentials()).toEqual({
      accessToken: null,
      organizationId: null,
    });
  });
});
