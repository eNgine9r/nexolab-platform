import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { SecuritySession } from "@/features/security/security-session";
import { Topbar } from "./topbar";

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: { children: ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const session: SecuritySession = {
  authenticated: true,
  identity: { id: "user-1", provider: "local", subject: "operator-1", email: null, displayName: "Оператор" },
  memberships: ["org-1", "org-2"].map((id, index) => ({
    organizationId: id,
    organizationSlug: id,
    organizationName: `Організація ${index + 1}`,
    roles: ["viewer"],
    permissions: ["dashboard.read"],
  })),
};

describe("Topbar operator actions", () => {
  it("offers real destinations and does not invent account or notification data", () => {
    render(<Topbar title="Огляд" onMenuOpen={vi.fn()} />);
    expect(screen.getByText("Огляд")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Відкрити тривоги" })).toHaveAttribute("href", "/alerts");
    expect(screen.getByRole("link", { name: "Нова сесія" })).toHaveAttribute("href", "/sessions/new");
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
    for (const text of ["24 липня 2026", "12", "Administrator", "Інженер", "Лабораторія 1", "⌘ K"]) {
      expect(screen.queryByText(text)).not.toBeInTheDocument();
    }
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("uses verified membership and invokes organization and account actions", () => {
    const select = vi.fn();
    const signOut = vi.fn();
    const menu = vi.fn();
    render(
      <Topbar
        title="Огляд"
        onMenuOpen={menu}
        securitySession={session}
        selectedMembership={session.memberships[0]}
        onOrganizationChange={select}
        onSignOut={signOut}
      />,
    );
    expect(screen.getByText("Оператор")).toBeInTheDocument();
    expect(screen.getByText("viewer")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Організація" }), { target: { value: "org-2" } });
    expect(select).toHaveBeenCalledExactlyOnceWith("org-2");
    fireEvent.click(screen.getByRole("button", { name: "Вийти з NEXOLAB" }));
    expect(signOut).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Відкрити меню" }));
    expect(menu).toHaveBeenCalledTimes(1);
  });

  it("shows a single organization as context without a redundant selector", () => {
    render(
      <Topbar
        title="Огляд"
        onMenuOpen={vi.fn()}
        securitySession={{ ...session, memberships: [session.memberships[0]] }}
        selectedMembership={session.memberships[0]}
        onOrganizationChange={vi.fn()}
      />,
    );
    expect(screen.getByText("Організація 1")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("keeps named session creation callbacks and supports hiding the action", () => {
    const create = vi.fn();
    const { rerender } = render(<Topbar title="Огляд" onMenuOpen={vi.fn()} onCreateSession={create} />);
    fireEvent.click(screen.getByRole("button", { name: "Нова сесія" }));
    expect(create).toHaveBeenCalledTimes(1);
    rerender(<Topbar title="Огляд" onMenuOpen={vi.fn()} showCreateSession={false} />);
    expect(screen.queryByRole("button", { name: "Нова сесія" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Нова сесія" })).not.toBeInTheDocument();
  });
});
