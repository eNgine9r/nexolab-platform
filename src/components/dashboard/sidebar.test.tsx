import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { platformNavItems, Sidebar } from "./sidebar";

vi.mock("next/navigation", () => ({
  usePathname: () => "/refrigeration/showcase-106-01",
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
