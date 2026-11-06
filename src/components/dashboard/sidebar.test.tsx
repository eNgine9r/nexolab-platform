import type { ReactNode } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { platformNavGroups, platformNavItems, Sidebar } from "./sidebar";
import type { SecurityMembership, SecuritySession } from "@/features/security/security-session";

const demo = { mode: "demo", state: "demo", session: null, membership: null } as const;

function liveSecurity(permissions: SecurityMembership["permissions"], administrator = false) {
  const membership: SecurityMembership = {
    organizationId: "lab-a",
    organizationSlug: "lab-a",
    organizationName: "Lab A",
    roles: administrator ? ["administrator"] : ["engineer"],
    permissions,
  };
  const session: SecuritySession = {
    authenticated: true,
    identity: { id: "user-1", provider: "local", subject: "user-1", email: null, displayName: null },
    memberships: [membership],
  };
  return { mode: "live" as const, state: "ready" as const, session, membership };
}

const navigation = vi.hoisted(() => ({ pathname: "/refrigeration/showcase-106-01" }));

vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
}));

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: { children: ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("./brand-logo", () => ({
  BrandLogo: () => <div>NEXOLAB</div>,
}));

describe("Sidebar", () => {
  it.each(["/equipment-layouts", "/equipment-layouts/layout-1"])(
    "does not activate equipment for %s",
    (pathname) => {
      navigation.pathname = pathname;
      render(<Sidebar security={demo} open onClose={() => undefined} />);
      expect(screen.getByRole("link", { name: "Схеми обладнання" })).toHaveAttribute("aria-current", "page");
      expect(screen.getByRole("link", { name: "Обладнання" })).not.toHaveAttribute("aria-current");
      expect(document.querySelectorAll('[aria-current="page"]')).toHaveLength(1);
      navigation.pathname = "/refrigeration/showcase-106-01";
    },
  );

  it("renders every platform destination as an internal route", () => {
    render(<Sidebar security={demo} open onClose={() => undefined} />);

    for (const item of platformNavItems) {
      expect(screen.getByRole("link", { name: item.label })).toHaveAttribute("href", item.href);
    }
    expect(screen.queryByRole("button", { name: "Live дані" })).not.toBeInTheDocument();
  });

  it("uses the pathname as the only active-navigation source", () => {
    render(
      <Sidebar
        security={demo}
        open
        activeItem="Камери"
        onClose={() => undefined}
        onSelect={() => undefined}
      />,
    );

    expect(screen.getByRole("link", { name: "Холодильне обладнання" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Камери" })).not.toHaveAttribute("aria-current");
  });

  it("does not fabricate service, network or cloud health", () => {
    render(<Sidebar security={demo} open onClose={() => undefined} />);

    expect(screen.getByRole("region", { name: "Профіль виконання" })).toHaveTextContent("LOCAL_LAN");
    expect(screen.queryByText("Усі сервіси в нормі")).not.toBeInTheDocument();
    expect(screen.queryByText("Online")).not.toBeInTheDocument();
    expect(screen.queryByText("Synced")).not.toBeInTheDocument();
    expect(screen.queryByText("Хмарна синхронізація")).not.toBeInTheDocument();
  });
});

it("groups each canonical destination once and describes planned Lockers", () => {
  render(<Sidebar security={demo} open onClose={vi.fn()} />);
  expect(screen.getAllByRole("link")).toHaveLength(13);
  expect(new Set(screen.getAllByRole("link").map((link) => link.getAttribute("href"))).size).toBe(13);
  for (const group of platformNavGroups) {
    const region = screen.getByRole("region", { name: group.label });
    expect(within(region).getAllByRole("link")).toHaveLength(group.items.length);
    for (const item of group.items)
      expect(within(region).getByRole("link", { name: item.label })).toHaveAttribute("href", item.href);
  }
  const lockers = screen.getByRole("link", { name: "Поштомати" });
  expect(lockers).toHaveAccessibleDescription("Заплановано");
  expect(within(lockers).getByText("Заплановано")).toBeVisible();
});

it("keeps canonical link clicks closing the mobile menu", () => {
  const onClose = vi.fn();
  render(<Sidebar security={demo} open onClose={onClose} />);
  fireEvent.click(screen.getByRole("link", { name: "Поштомати" }));
  expect(onClose).toHaveBeenCalledOnce();
});

it("shows only destinations permitted by the selected membership", () => {
  const security = liveSecurity([
    "telemetry.read",
    "reports.read",
    "navigation.live",
    "navigation.energy",
    "navigation.reports",
  ]);
  render(<Sidebar security={security} open onClose={vi.fn()} />);
  for (const label of ["Live дані", "Енергомоніторинг", "Звіти", "Налаштування"]) {
    expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
  }
  for (const label of ["Огляд", "Вузли", "Тривоги", "Камери", "Поштомати", "Обладнання"]) {
    expect(screen.queryByRole("link", { name: label })).not.toBeInTheDocument();
  }
});

it("hides navigation on missing, loading or invalid membership and removes empty groups", () => {
  const security = liveSecurity(["reports.read"]);
  const { rerender } = render(<Sidebar security={security} open onClose={vi.fn()} />);
  expect(screen.queryByRole("region", { name: "Моніторинг" })).not.toBeInTheDocument();
  rerender(<Sidebar security={{ ...security, state: "loading" }} open onClose={vi.fn()} />);
  expect(screen.queryAllByRole("link")).toHaveLength(0);
  rerender(
    <Sidebar
      security={{ ...security, membership: { ...security.membership, organizationId: "unknown" } }}
      open
      onClose={vi.fn()}
    />,
  );
  expect(screen.queryAllByRole("link")).toHaveLength(0);
  rerender(<Sidebar security={undefined} open onClose={vi.fn()} />);
  expect(screen.queryAllByRole("link")).toHaveLength(0);
});

it("recomputes permissions on organization changes and logout", () => {
  const first = liveSecurity(["dashboard.read", "navigation.overview"]);
  const other = {
    ...first.membership,
    organizationId: "lab-b",
    permissions: ["reports.read", "navigation.reports"] as const,
  };
  const session = {
    ...first.session,
    memberships: [first.membership, { ...other, permissions: [...other.permissions] }],
  };
  const { rerender } = render(<Sidebar security={{ ...first, session }} open onClose={vi.fn()} />);
  expect(screen.getByRole("link", { name: "Огляд" })).toBeInTheDocument();
  rerender(
    <Sidebar security={{ ...first, session, membership: session.memberships[1] }} open onClose={vi.fn()} />,
  );
  expect(screen.queryByRole("link", { name: "Огляд" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Звіти" })).toBeInTheDocument();
  rerender(
    <Sidebar
      security={{ ...first, state: "unauthenticated", session: null, membership: null }}
      open
      onClose={vi.fn()}
    />,
  );
  expect(screen.queryAllByRole("link")).toHaveLength(0);
});

it("removes an entry when the refreshed session revokes its permission", () => {
  const before = liveSecurity(["alerts.read", "navigation.alerts"]);
  const { rerender } = render(<Sidebar security={before} open onClose={vi.fn()} />);
  expect(screen.getByRole("link", { name: "Тривоги" })).toBeInTheDocument();
  const after = liveSecurity([]);
  rerender(<Sidebar security={after} open onClose={vi.fn()} />);
  expect(screen.queryByRole("link", { name: "Тривоги" })).not.toBeInTheDocument();
});

it("keeps administrator-only placeholders and cameras hidden from other roles", () => {
  const security = liveSecurity(["dashboard.read", "navigation.cameras", "navigation.lockers"], true);
  const { rerender } = render(<Sidebar security={security} open onClose={vi.fn()} />);
  expect(screen.getByRole("link", { name: "Камери" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Поштомати" })).toBeInTheDocument();
  rerender(<Sidebar security={liveSecurity(["dashboard.read"])} open onClose={vi.fn()} />);
  expect(screen.queryByRole("link", { name: "Камери" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Поштомати" })).not.toBeInTheDocument();
});

it("requires each page grant separately even when resource access is shared", () => {
  const security = liveSecurity(["telemetry.read", "navigation.live"]);
  const { rerender } = render(<Sidebar security={security} open onClose={vi.fn()} />);
  expect(screen.getByRole("link", { name: "Live дані" })).toBeVisible();
  expect(screen.queryByRole("link", { name: "Енергомоніторинг" })).not.toBeInTheDocument();
  rerender(<Sidebar security={liveSecurity(["navigation.live"])} open onClose={vi.fn()} />);
  expect(screen.queryByRole("link", { name: "Live дані" })).not.toBeInTheDocument();
});

it("allows a specifically granted camera page for a non-administrator", () => {
  const user = liveSecurity(["navigation.cameras"]);
  render(<Sidebar security={user} open onClose={vi.fn()} />);
  expect(screen.getByRole("link", { name: "Камери" })).toBeVisible();
  expect(screen.queryByRole("link", { name: "Поштомати" })).not.toBeInTheDocument();
});
