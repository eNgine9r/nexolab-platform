import { useState, type ReactNode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DashboardSecurityModel } from "@/hooks/use-dashboard-security";
import {
  RefrigerationAccountTopbar,
  RefrigerationSecurityBoundary,
  useRefrigerationAccount,
} from "./refrigeration-security-boundary";

const mock = vi.hoisted(() => ({
  security: null as DashboardSecurityModel | null,
  pathname: "/refrigeration/item-a",
  replace: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mock.replace }),
  usePathname: () => mock.pathname,
}));
vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: { children: ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));
vi.mock("@/hooks/use-dashboard-security", () => ({
  useDashboardSecurity: () => mock.security,
}));

function ready(organizationId = "org-a"): DashboardSecurityModel {
  const memberships = ["org-a", "org-b"].map((id) => ({
    organizationId: id,
    organizationSlug: id,
    organizationName: id,
    roles: ["viewer" as const],
    permissions: ["dashboard.read" as const],
  }));
  return {
    mode: "live",
    state: "ready",
    error: null,
    errorCode: null,
    diagnostics: null,
    session: {
      authenticated: true,
      identity: {
        id: "operator",
        provider: "local",
        subject: "operator",
        email: null,
        displayName: "Перевірений оператор",
      },
      memberships,
    },
    membership: memberships.find((m) => m.organizationId === organizationId)!,
    selectOrganization: vi.fn(),
    signOut: vi.fn(async () => {}),
    retry: vi.fn(),
  };
}

function Workspace() {
  const account = useRefrigerationAccount();
  const [draft, setDraft] = useState("");
  return (
    <>
      <RefrigerationAccountTopbar title="Каталог" onMenuOpen={vi.fn()} />
      <span data-testid="scope">{account?.security.membership?.organizationId}</span>
      <input
        aria-label="Локальна чернетка"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
      />
    </>
  );
}

beforeEach(() => {
  mock.security = ready();
  mock.pathname = "/refrigeration/item-a";
  mock.replace.mockClear();
});

describe("Refrigeration shared account boundary", () => {
  it.each(["loading", "unauthenticated", "forbidden", "error"] as const)(
    "does not mount domain content for %s",
    (state) => {
      mock.security = { ...ready(), state, session: null, membership: null };
      render(
        <RefrigerationSecurityBoundary>
          <Workspace />
        </RefrigerationSecurityBoundary>,
      );
      expect(screen.queryByTestId("scope")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Вийти з NEXOLAB" })).not.toBeInTheDocument();
    },
  );

  it("forwards verified identity and hides session creation for a viewer", () => {
    render(
      <RefrigerationSecurityBoundary>
        <Workspace />
      </RefrigerationSecurityBoundary>,
    );
    expect(screen.getByText("Перевірений оператор")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Організація" })).toHaveValue("org-a");
    expect(screen.queryByRole("link", { name: "Нова сесія" })).not.toBeInTheDocument();
  });

  it("returns detail users to catalog and remounts retained local state for a new organization", () => {
    const initial = mock.security!;
    const { rerender } = render(
      <RefrigerationSecurityBoundary>
        <Workspace />
      </RefrigerationSecurityBoundary>,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Локальна чернетка" }), {
      target: { value: "old equipment draft" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Організація" }), { target: { value: "org-b" } });
    expect(initial.selectOrganization).toHaveBeenCalledExactlyOnceWith("org-b");
    expect(mock.replace).toHaveBeenCalledExactlyOnceWith("/refrigeration");
    mock.security = ready("org-b");
    rerender(
      <RefrigerationSecurityBoundary>
        <Workspace />
      </RefrigerationSecurityBoundary>,
    );
    expect(screen.getByTestId("scope")).toHaveTextContent("org-b");
    expect(screen.getByRole("textbox", { name: "Локальна чернетка" })).toHaveValue("");
  });

  it("clears the account through the shared sign-out before returning to login", async () => {
    const security = mock.security!;
    render(
      <RefrigerationSecurityBoundary>
        <Workspace />
      </RefrigerationSecurityBoundary>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Вийти з NEXOLAB" }));
    expect(security.signOut).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(mock.replace).toHaveBeenCalledExactlyOnceWith("/login"));
  });

  it("keeps explicit demo available without inventing account identity", () => {
    mock.security = { ...ready(), mode: "demo", state: "demo", session: null, membership: null };
    render(
      <RefrigerationSecurityBoundary>
        <Workspace />
      </RefrigerationSecurityBoundary>,
    );
    expect(screen.getByTestId("scope")).toBeInTheDocument();
    expect(screen.queryByText("Перевірений оператор")).not.toBeInTheDocument();
    expect(screen.queryByText("Administrator")).not.toBeInTheDocument();
  });
});
