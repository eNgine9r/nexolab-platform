import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DashboardSecurityModel } from "@/hooks/use-dashboard-security";

import { AlertsTelemetryScope } from "./alerts-telemetry-scope";

const mock = vi.hoisted(() => ({
  security: null as DashboardSecurityModel | null,
  inventory: vi.fn(),
}));

vi.mock("@/hooks/use-dashboard-security", () => ({
  useDashboardSecurity: () => mock.security,
}));

vi.mock("@/hooks/use-live-dashboard-inventory", () => ({
  useLiveDashboardInventory: (options: { enabled: boolean; organizationId: string | null }) => {
    mock.inventory(options);
    return {
      items: [],
      status: options.enabled ? "ready" : "idle",
      error: null,
      retry: vi.fn(),
    };
  },
}));

vi.mock("@/components/dashboard/security-gate", () => ({
  SecurityGate: ({ state }: { state: string }) => <div data-testid="security-gate" data-state={state} />,
}));

vi.mock("./alerts-workspace", () => ({
  AlertsWorkspace: () => <div data-testid="alerts-workspace" />,
}));

function readySecurity(): DashboardSecurityModel {
  const membership = {
    organizationId: "org-a",
    organizationSlug: "org-a",
    organizationName: "Organization A",
    roles: ["viewer" as const],
    permissions: ["alerts.read" as const],
  };
  return {
    mode: "live",
    state: "ready",
    session: {
      authenticated: true,
      identity: {
        id: "viewer-a",
        provider: "local",
        subject: "viewer-a",
        email: null,
        displayName: "Viewer A",
      },
      memberships: [membership],
    },
    membership,
    error: null,
    errorCode: null,
    diagnostics: null,
    selectOrganization: vi.fn(),
    retry: vi.fn(),
    signOut: vi.fn(async () => {}),
  };
}

beforeEach(() => {
  mock.inventory.mockClear();
  mock.security = readySecurity();
});

describe("AlertsTelemetryScope security boundary", () => {
  it.each(["loading", "unauthenticated", "forbidden", "error"] as const)(
    "keeps Alerts and inventory inactive while security is %s",
    (state) => {
      mock.security = {
        ...readySecurity(),
        state,
        session: state === "loading" ? readySecurity().session : null,
        membership: null,
        error: state === "error" ? "Session API unavailable" : null,
      };

      render(<AlertsTelemetryScope />);

      expect(screen.getByTestId("security-gate")).toHaveAttribute("data-state", state);
      expect(screen.queryByTestId("alerts-workspace")).not.toBeInTheDocument();
      expect(mock.inventory).toHaveBeenLastCalledWith({ enabled: false, organizationId: null });
    },
  );

  it("uses the verified membership scope after authentication", () => {
    render(<AlertsTelemetryScope />);

    expect(screen.queryByTestId("security-gate")).not.toBeInTheDocument();
    expect(screen.getByTestId("alerts-workspace")).toBeInTheDocument();
    expect(mock.inventory).toHaveBeenLastCalledWith({ enabled: true, organizationId: "org-a" });
  });

  it("preserves the existing demo-mode workspace behavior", () => {
    mock.security = {
      ...readySecurity(),
      mode: "demo",
      state: "demo",
      session: null,
      membership: null,
    };

    render(<AlertsTelemetryScope />);

    expect(screen.queryByTestId("security-gate")).not.toBeInTheDocument();
    expect(screen.getByTestId("alerts-workspace")).toBeInTheDocument();
    expect(mock.inventory).toHaveBeenLastCalledWith({ enabled: true, organizationId: null });
  });
});
