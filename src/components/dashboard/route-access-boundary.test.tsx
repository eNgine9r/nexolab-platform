import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SecurityMembership, SecuritySession } from "@/features/security/security-session";

const mock = vi.hoisted(() => ({ pathname: "/reports/report-1", security: null as unknown }));
vi.mock("next/navigation", () => ({
  usePathname: () => mock.pathname,
  useRouter: () => ({ replace: vi.fn() }),
}));
vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: { children: ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));
vi.mock("@/hooks/use-dashboard-security", () => ({ useDashboardSecurity: () => mock.security }));
vi.mock("./brand-logo", () => ({ BrandLogo: () => <span>NEXOLAB</span> }));

import { RouteAccessBoundary } from "./route-access-boundary";

function security(permissions: SecurityMembership["permissions"]) {
  const membership: SecurityMembership = {
    organizationId: "lab",
    organizationSlug: "lab",
    organizationName: "Lab",
    roles: ["viewer"],
    permissions,
  };
  const session: SecuritySession = {
    authenticated: true,
    identity: { id: "user", subject: "user", provider: "local", email: null, displayName: null },
    memberships: [membership],
  };
  return {
    mode: "live",
    state: "ready",
    membership,
    session,
    error: null,
    errorCode: null,
    diagnostics: null,
    retry: vi.fn(),
    signOut: vi.fn(),
    selectOrganization: vi.fn(),
  };
}

describe("RouteAccessBoundary", () => {
  beforeEach(() => {
    mock.pathname = "/reports/report-1";
    mock.security = security(["reports.read", "navigation.reports"]);
  });
  it("does not mount a nested page without its page grant or resource prerequisite", () => {
    mock.security = security(["reports.read"]);
    const { rerender } = render(
      <RouteAccessBoundary>
        <div>Protected child</div>
      </RouteAccessBoundary>,
    );
    expect(screen.queryByText("Protected child")).not.toBeInTheDocument();
    expect(screen.getByText("Доступ до сторінки не надано")).toBeVisible();
    mock.security = security(["navigation.reports"]);
    rerender(
      <RouteAccessBoundary>
        <div>Protected child</div>
      </RouteAccessBoundary>,
    );
    expect(screen.queryByText("Protected child")).not.toBeInTheDocument();
    mock.security = security(["reports.read", "navigation.reports"]);
    rerender(
      <RouteAccessBoundary>
        <div>Protected child</div>
      </RouteAccessBoundary>,
    );
    expect(screen.getByText("Protected child")).toBeVisible();
    mock.security = security(["reports.read"]);
    rerender(
      <RouteAccessBoundary>
        <div>Protected child</div>
      </RouteAccessBoundary>,
    );
    expect(screen.queryByText("Protected child")).not.toBeInTheDocument();
  });
  it("gates the instruments settings page independently from dashboard access", () => {
    mock.pathname = "/settings/instrumentation";
    mock.security = security(["dashboard.read"]);
    const { rerender } = render(
      <RouteAccessBoundary>
        <div>Instruments content</div>
      </RouteAccessBoundary>,
    );
    expect(screen.queryByText("Instruments content")).not.toBeInTheDocument();
    mock.security = security(["dashboard.read", "navigation.instrumentation"]);
    rerender(
      <RouteAccessBoundary>
        <div>Instruments content</div>
      </RouteAccessBoundary>,
    );
    expect(screen.getByText("Instruments content")).toBeVisible();
  });
  it("does not mount protected content while authentication is loading or after logout", () => {
    mock.security = {
      ...security(["reports.read", "navigation.reports"]),
      state: "loading",
      session: null,
      membership: null,
    };
    const { rerender } = render(
      <RouteAccessBoundary>
        <div>Protected child</div>
      </RouteAccessBoundary>,
    );
    expect(screen.queryByText("Protected child")).not.toBeInTheDocument();
    mock.security = { ...security([]), state: "unauthenticated", session: null, membership: null };
    rerender(
      <RouteAccessBoundary>
        <div>Protected child</div>
      </RouteAccessBoundary>,
    );
    expect(screen.queryByText("Protected child")).not.toBeInTheDocument();
    expect(screen.getByText("Потрібен вхід до системи")).toBeVisible();
  });
  it.each(["/login", "/telegram-miniapp", "/telegram-miniapp/report", "/api/runtime-identity"])(
    "leaves %s outside the page gate",
    (path) => {
      mock.pathname = path;
      mock.security = null;
      render(
        <RouteAccessBoundary>
          <div>Unrelated child</div>
        </RouteAccessBoundary>,
      );
      expect(screen.getByText("Unrelated child")).toBeVisible();
    },
  );
  it("allows explicit demo mode", () => {
    mock.security = { mode: "demo" };
    render(
      <RouteAccessBoundary>
        <div>Demo child</div>
      </RouteAccessBoundary>,
    );
    expect(screen.getByText("Demo child")).toBeVisible();
  });
});
