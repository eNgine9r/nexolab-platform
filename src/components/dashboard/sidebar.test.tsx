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
    render(<Sidebar open activeItem="" onClose={() => undefined} onSelect={() => undefined} />);

    for (const item of platformNavItems) {
      expect(screen.getByRole("link", { name: item.label })).toHaveAttribute("href", item.href);
    }
    expect(screen.queryByRole("button", { name: "Live дані" })).not.toBeInTheDocument();
  });

  it("keeps the refrigeration navigation item active on detail routes", () => {
    render(<Sidebar open activeItem="" onClose={() => undefined} onSelect={() => undefined} />);

    expect(screen.getByRole("link", { name: "Холодильне обладнання" })).toHaveClass("text-white");
  });
});
