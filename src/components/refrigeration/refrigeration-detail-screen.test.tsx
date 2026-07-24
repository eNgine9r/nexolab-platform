import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { getRefrigerationEquipment } from "@/data/refrigeration";

import { RefrigerationDetailScreen } from "./refrigeration-detail-screen";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => <a href={href}>{children}</a>,
}));

vi.mock("@/components/dashboard/sidebar", () => ({
  Sidebar: () => <div data-testid="sidebar" />,
}));

vi.mock("@/components/dashboard/topbar", () => ({
  Topbar: ({ title }: { title: string }) => <div>{title}</div>,
}));

function referenceEquipment() {
  const equipment = getRefrigerationEquipment("showcase-106-01");

  if (!equipment) {
    throw new Error("Reference refrigeration equipment fixture is missing");
  }

  return equipment;
}

async function waitForLayout() {
  await screen.findByRole("button", {
    name: "Вибрати датчик 01F на схемі",
  });
}

describe("RefrigerationDetailScreen", () => {
  it("filters the image and list by sensor side and shelf", async () => {
    render(<RefrigerationDetailScreen equipment={referenceEquipment()} />);
    await waitForLayout();

    expect(screen.getByText("Показано 48 із 48")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Задній фронт" }));
    expect(screen.getByText("Показано 24 із 48")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Фільтр за полицею"), {
      target: { value: "2" },
    });
    expect(screen.getByText("Показано 6 із 48")).toBeInTheDocument();
    expect(
      await screen.findByRole("button", {
        name: "Вибрати датчик 07R на схемі",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "Вибрати датчик 01R на схемі",
      }),
    ).not.toBeInTheDocument();
  });

  it("keeps marker and list selection synchronized", async () => {
    render(<RefrigerationDetailScreen equipment={referenceEquipment()} />);
    await waitForLayout();

    fireEvent.click(
      screen.getByRole("button", {
        name: "Вибрати датчик 08F зі списку",
      }),
    );

    expect(screen.getByText("08F · Передній фронт 08")).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Вибрати датчик 08F на схемі",
      }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", {
        name: "Вибрати датчик 08F зі списку",
      }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("selects the first visible sensor when the active filter hides the previous selection", async () => {
    render(<RefrigerationDetailScreen equipment={referenceEquipment()} />);
    await waitForLayout();

    fireEvent.click(screen.getByRole("button", { name: "Задній фронт" }));

    expect(screen.getByText("01R · Задній фронт 01")).toBeInTheDocument();
    expect(
      await screen.findByRole("button", {
        name: "Вибрати датчик 01R на схемі",
      }),
    ).toHaveAttribute("aria-pressed", "true");
  });
});
