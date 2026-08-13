import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { VersionScreen } from "./version-screen";

const security = vi.hoisted(() => ({
  value: {
    mode: "live",
    state: "ready",
    session: {
      authenticated: true,
      identity: {
        id: "engineer-id",
        provider: "nexolab-local",
        subject: "engineer",
        email: null,
        displayName: "Engineer",
      },
      memberships: [],
    },
    membership: {
      organizationId: "11111111-1111-1111-1111-111111111111",
      organizationSlug: "nexolab",
      organizationName: "NEXOLAB",
      roles: ["engineer"],
      permissions: ["dashboard.read"],
    },
    error: null,
    errorCode: null,
    diagnostics: null,
    retry: vi.fn(),
    selectOrganization: vi.fn(),
    signOut: vi.fn(),
  },
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("@/hooks/use-dashboard-security", () => ({ useDashboardSecurity: () => security.value }));
vi.mock("@/lib/telemetry/runtime-config", () => ({
  getTelemetryRuntimeConfig: () => ({ mode: "live", apiBaseUrl: "http://127.0.0.1:8082" }),
}));

describe("VersionScreen authorization boundary", () => {
  beforeEach(() => {
    security.value.mode = "live";
    security.value.membership.permissions = ["dashboard.read"];
  });

  it("does not initialize version management for a non-administrator", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    render(<VersionScreen />);

    expect(screen.getByRole("heading", { name: "Доступ заборонено" })).toBeVisible();
    expect(screen.getByText(/project_versions\.manage/)).toBeVisible();
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("does not expose host controls in demo mode", () => {
    security.value.mode = "demo";

    render(<VersionScreen />);

    expect(screen.getByRole("heading", { name: "Version management недоступний у demo mode" })).toBeVisible();
  });
});
