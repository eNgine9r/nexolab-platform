import type { ReactNode } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { platformNavGroups, platformNavItems, Sidebar } from "./sidebar";

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
      render(<Sidebar open onClose={() => undefined} />);
      expect(screen.getByRole("link", { name: "Схеми обладнання" })).toHaveAttribute("aria-current", "page");
      expect(screen.getByRole("link", { name: "Обладнання" })).not.toHaveAttribute("aria-current");
      expect(document.querySelectorAll('[aria-current="page"]')).toHaveLength(1);
      navigation.pathname = "/refrigeration/showcase-106-01";
    },
  );

  it("renders every platform destination as an internal route", () => {
    render(<Sidebar open onClose={() => undefined} />);

    for (const item of platformNavItems) {
      expect(screen.getByRole("link", { name: item.label })).toHaveAttribute("href", item.href);
    }
    expect(screen.queryByRole("button", { name: "Live дані" })).not.toBeInTheDocument();
  });

  it("uses the pathname as the only active-navigation source", () => {
    render(<Sidebar open activeItem="Камери" onClose={() => undefined} onSelect={() => undefined} />);

    expect(screen.getByRole("link", { name: "Холодильне обладнання" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Камери" })).not.toHaveAttribute("aria-current");
  });

  it("does not fabricate service, network or cloud health", () => {
    render(<Sidebar open onClose={() => undefined} />);

    expect(screen.getByRole("region", { name: "Профіль виконання" })).toHaveTextContent("LOCAL_LAN");
    expect(screen.queryByText("Усі сервіси в нормі")).not.toBeInTheDocument();
    expect(screen.queryByText("Online")).not.toBeInTheDocument();
    expect(screen.queryByText("Synced")).not.toBeInTheDocument();
    expect(screen.queryByText("Хмарна синхронізація")).not.toBeInTheDocument();
  });
});

it("groups each canonical destination once and describes planned Lockers", () => {
  render(<Sidebar open onClose={vi.fn()} />);
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
  render(<Sidebar open onClose={onClose} />);
  fireEvent.click(screen.getByRole("link", { name: "Поштомати" }));
  expect(onClose).toHaveBeenCalledOnce();
});
