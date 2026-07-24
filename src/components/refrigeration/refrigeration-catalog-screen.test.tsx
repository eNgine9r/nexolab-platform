import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RefrigerationCatalogScreen } from "./refrigeration-catalog-screen";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => <a href={href}>{children}</a>,
}));

vi.mock("@/components/dashboard/sidebar", () => ({
  Sidebar: () => <div data-testid="sidebar" />,
}));

vi.mock("@/components/dashboard/topbar", () => ({
  Topbar: ({ title }: { title: string }) => <div>{title}</div>,
}));

describe("RefrigerationCatalogScreen", () => {
  it("filters equipment by search text", () => {
    render(<RefrigerationCatalogScreen />);

    expect(screen.getByText("Вітрина №106-01")).toBeInTheDocument();
    expect(screen.getByText("Холодильна камера №201")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Пошук обладнання"), {
      target: { value: "Compact 900" },
    });

    expect(screen.getByText("Вітрина №107-02")).toBeInTheDocument();
    expect(screen.queryByText("Вітрина №106-01")).not.toBeInTheDocument();
    expect(screen.queryByText("Холодильна камера №201")).not.toBeInTheDocument();
  });

  it("filters equipment by operational status", () => {
    render(<RefrigerationCatalogScreen />);

    fireEvent.change(screen.getByLabelText("Фільтр за станом"), {
      target: { value: "warning" },
    });

    expect(screen.getByText("Вітрина №107-02")).toBeInTheDocument();
    expect(screen.queryByText("Вітрина №106-01")).not.toBeInTheDocument();
  });

  it("renders an explicit empty state when no equipment matches", () => {
    render(<RefrigerationCatalogScreen />);

    fireEvent.change(screen.getByPlaceholderText("Пошук обладнання"), {
      target: { value: "does-not-exist" },
    });

    expect(screen.getByText("Обладнання не знайдено")).toBeInTheDocument();
  });
});
