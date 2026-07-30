import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
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
  it("uses one expanded workspace without duplicated passport or live-sensor sidebars", async () => {
    const equipment = referenceEquipment();
    render(<RefrigerationDetailScreen equipment={equipment} />);
    await waitForLayout();

    expect(screen.getByText("Паспорт, lifecycle, фото та bindings")).toBeInTheDocument();
    expect(screen.queryByText("Поточний стан")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Датчики в реальному часі" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Фото обладнання", { selector: "h2" }),
    ).not.toBeInTheDocument();
    if (equipment.climateChamberId) {
      expect(
        screen.getAllByText("Кліматична камера", { exact: true }).length,
      ).toBeGreaterThan(0);
    }
    expect(screen.queryByText(/48 bindings/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Редагувати схему та датчики" }),
    ).toBeInTheDocument();
  });

  it("filters only the markers on the central image by side and shelf", async () => {
    render(<RefrigerationDetailScreen equipment={referenceEquipment()} />);
    await waitForLayout();

    expect(
      screen.getByRole("button", { name: "Вибрати датчик 01F на схемі" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Вибрати датчик 01R на схемі" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Задній фронт" }));
    expect(
      screen.queryByRole("button", { name: "Вибрати датчик 01F на схемі" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Вибрати датчик 01R на схемі" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Полиця 2" }));
    expect(
      screen.getByRole("button", { name: "Вибрати датчик 07R на схемі" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Вибрати датчик 01R на схемі" }),
    ).not.toBeInTheDocument();
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
