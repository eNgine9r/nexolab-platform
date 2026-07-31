import type { ReactNode } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { getRefrigerationEquipment } from "@/data/refrigeration";

import { RefrigerationDetailScreen } from "./refrigeration-detail-screen";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/components/dashboard/sidebar", () => ({
  Sidebar: () => <div data-testid="sidebar" />,
}));

vi.mock("@/components/dashboard/topbar", () => ({
  Topbar: ({ title }: { title: string }) => <div>{title}</div>,
}));

function referenceEquipment() {
  const equipment = getRefrigerationEquipment("showcase-106-01");
  if (!equipment) throw new Error("Reference refrigeration equipment fixture is missing");
  return equipment;
}

async function waitForLayout() {
  await screen.findByRole("button", { name: "Вибрати датчик 01F на схемі" });
}

describe("RefrigerationDetailScreen", () => {
  it("keeps passport and lifecycle controls out of the primary canvas flow", async () => {
    const equipment = referenceEquipment();
    render(<RefrigerationDetailScreen equipment={equipment} />);
    await waitForLayout();

    expect(
      screen.queryByText("Паспорт, lifecycle, фото та bindings"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("dialog", { name: "Паспорт обладнання" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Відкрити паспорт обладнання" })).toBeInTheDocument();
    expect(screen.getByTitle("Доступ оператора")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Відкрити версії та публікацію схеми" }),
    ).toBeInTheDocument();
    expect(document.querySelectorAll("#layout-editor")).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Відкрити паспорт обладнання" }));
    expect(
      screen.getByRole("dialog", { name: "Паспорт обладнання" }),
    ).toBeInTheDocument();
  });

  it("filters markers from the compact canvas toolbar", async () => {
    render(<RefrigerationDetailScreen equipment={referenceEquipment()} />);
    await waitForLayout();

    expect(
      screen.getByRole("button", { name: "Вибрати датчик 01F на схемі" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Вибрати датчик 01R на схемі" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByTitle("Фільтри датчиків"));
    const filterMenu = screen.getByText("Відображення датчиків").parentElement?.parentElement;
    if (!filterMenu) throw new Error("Filter menu is missing");

    fireEvent.click(within(filterMenu).getByRole("button", { name: "Задній фронт" }));
    expect(
      screen.queryByRole("button", { name: "Вибрати датчик 01F на схемі" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Вибрати датчик 01R на схемі" }),
    ).toBeInTheDocument();

    fireEvent.click(within(filterMenu).getByRole("button", { name: "2" }));
    expect(
      screen.getByRole("button", { name: "Вибрати датчик 07R на схемі" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Вибрати датчик 01R на схемі" }),
    ).not.toBeInTheDocument();
  });

  it("uses scroll-free contour fit by default and keeps manual zoom available", async () => {
    render(<RefrigerationDetailScreen equipment={referenceEquipment()} />);
    await waitForLayout();

    const workspace = screen.getByTestId("equipment-image-workspace");
    const viewport = screen.getByTestId("equipment-image-viewport");
    const stage = screen.getByTestId("equipment-image-stage");
    const fitButton = screen.getByRole("button", {
      name: "Заповнити контур без прокручування",
    });

    expect(workspace).toHaveAttribute("data-fit-contour", "true");
    expect(stage).toHaveAttribute("data-fit-contour", "true");
    expect(viewport.className).toContain("overflow-hidden");
    expect(fitButton).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(fitButton);
    expect(workspace).toHaveAttribute("data-fit-contour", "false");
    expect(viewport.className).toContain("overflow-auto");
  });

  it("keeps marker selection in the central canvas without a duplicated sensor list", async () => {
    render(<RefrigerationDetailScreen equipment={referenceEquipment()} />);
    await waitForLayout();

    const marker = screen.getByRole("button", { name: "Вибрати датчик 08F на схемі" });
    fireEvent.click(marker);

    expect(marker).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.queryByRole("button", { name: "Вибрати датчик 08F зі списку" }),
    ).not.toBeInTheDocument();
  });
});
