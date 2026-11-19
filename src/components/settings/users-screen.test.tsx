import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UsersScreen } from "./users-screen";

const auth = vi.hoisted(() => ({
  credentials: vi.fn(),
  retry: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/settings/users",
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/components/dashboard/sidebar", () => ({ Sidebar: () => null }));
vi.mock("@/components/dashboard/topbar", () => ({ Topbar: () => null }));
vi.mock("@/hooks/use-display-time-zone", () => ({ useDisplayTimeZone: () => "UTC" }));

vi.mock("@/lib/telemetry/runtime-config", () => ({
  getTelemetryRuntimeConfig: () => ({ mode: "live", apiBaseUrl: "http://127.0.0.1:8082" }),
}));

vi.mock("@/features/security/auth-runtime", () => ({
  createRuntimeCredentialProvider: () => auth.credentials,
}));

vi.mock("@/hooks/use-dashboard-security", () => {
  const security = {
    mode: "live",
    state: "ready",
    session: {},
    membership: { organizationId: "test-organization", permissions: ["memberships.manage"] },
    retry: auth.retry,
  };
  return { useDashboardSecurity: () => security };
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const createdUser = {
  id: "test-account",
  identity_id: "test-identity",
  username: "new-operator",
  is_active: true,
  role: "laboratory_technician",
  legacy_roles: [],
  granted_permissions: [],
  effective_permissions: [],
  created_at: "2026-11-16T08:00:00Z",
  password_changed_at: "2026-11-16T08:00:00Z",
  last_authenticated_at: "2026-11-16T08:00:00Z",
};

describe("UsersScreen authorization", () => {
  afterEach(() => {
    cleanup();
    vi.resetAllMocks();
    vi.unstubAllGlobals();
  });

  it.each([
    [201, "Користувача new-operator створено."],
    [401, "Потрібен вхід до системи"],
    [403, "Forbidden (forbidden)"],
  ])("handles create HTTP %s with the current credentials", async (status, message) => {
    auth.credentials.mockResolvedValue({
      accessToken: "initial-bearer",
      organizationId: "test-organization",
    });
    const fetchMock = vi.fn<typeof fetch>(async (_input, init) => {
      if (init?.method !== "POST") return jsonResponse({ items: [] });
      if (status === 201) return jsonResponse(createdUser, status);
      return jsonResponse({ detail: { code: "forbidden", message: "Forbidden" } }, status);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<UsersScreen />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    auth.credentials.mockResolvedValue({
      accessToken: "current-bearer",
      organizationId: "test-organization",
    });
    fireEvent.click(screen.getByRole("button", { name: "Новий користувач" }));
    fireEvent.change(screen.getByLabelText("Логін"), { target: { value: "new-operator" } });
    fireEvent.change(screen.getByLabelText("Початковий пароль"), { target: { value: "fixture-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Створити" }));

    expect(await screen.findByText(message)).toBeInTheDocument();
    const createRequest = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(createRequest?.[0]).toBe("http://127.0.0.1:8082/api/v1/admin/users");
    const headers = new Headers(createRequest?.[1]?.headers);
    expect(headers.get("Authorization")).toBe("Bearer current-bearer");
    expect(headers.get("X-Organization-ID")).toBe("test-organization");
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);

    if (status === 401) {
      expect(screen.getByRole("link", { name: "Увійти" })).toBeVisible();
      expect(screen.queryByRole("button", { name: "Новий користувач" })).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Повторити перевірку" }));
      expect(auth.retry).toHaveBeenCalledOnce();
    }
  });
});
