import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { getRefrigerationEquipment } from "@/data/refrigeration";

import { RefrigerationLayoutEditorScreen } from "./refrigeration-layout-editor-screen";

vi.mock("next/image", () => ({
  default: () => <div data-testid="equipment-image" />,
}));

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

  if (!equipment) {
    throw new Error("Reference refrigeration equipment fixture is missing");
  }

  return equipment;
}

describe("RefrigerationLayoutEditorScreen", () => {
  it("protects marker positions in view mode", () => {
    render(<RefrigerationLayoutEditorScreen equipment={referenceEquipment()} />);

    const marker = screen.getByRole("button", {
      name: "Вибрати датчик 01F",
    });
    fireEvent.keyDown(marker, { key: "ArrowRight" });

    expect(screen.queryByText("Незбережені зміни")).not.toBeInTheDocument();
    expect(screen.getByText("Режим перегляду")).toBeInTheDocument();
  });

  it("moves a marker with the keyboard and exposes the dirty draft state", () => {
    render(<RefrigerationLayoutEditorScreen equipment={referenceEquipment()} />);

    fireEvent.click(screen.getByRole("button", { name: "Редагувати" }));
    fireEvent.keyDown(
      screen.getByRole("button", { name: "Перемістити датчик 01F" }),
      { key: "ArrowRight" },
    );

    expect(screen.getByText("Незбережені зміни")).toBeInTheDocument();
    expect(screen.getByText("Режим редагування")).toBeInTheDocument();
    expect(screen.getByText("Є незбережені")).toBeInTheDocument();
  });

  it("resets draft coordinates without leaving edit mode", () => {
    render(<RefrigerationLayoutEditorScreen equipment={referenceEquipment()} />);

    fireEvent.click(screen.getByRole("button", { name: "Редагувати" }));
    fireEvent.keyDown(
      screen.getByRole("button", { name: "Перемістити датчик 01F" }),
      { key: "ArrowDown", shiftKey: true },
    );
    expect(screen.getByText("Незбережені зміни")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Скинути" }));

    expect(screen.queryByText("Незбережені зміни")).not.toBeInTheDocument();
    expect(screen.getByText("Режим редагування")).toBeInTheDocument();
    expect(screen.getByText("Немає")).toBeInTheDocument();
  });

  it("requires an explicit discard decision before leaving a dirty draft", () => {
    render(<RefrigerationLayoutEditorScreen equipment={referenceEquipment()} />);

    fireEvent.click(screen.getByRole("button", { name: "Редагувати" }));
    fireEvent.keyDown(
      screen.getByRole("button", { name: "Перемістити датчик 01F" }),
      { key: "ArrowLeft" },
    );
    fireEvent.click(screen.getByRole("button", { name: "Вийти" }));

    expect(screen.getByText("Відкинути незбережені зміни?")).toBeInTheDocument();
    expect(screen.getByText("Режим редагування")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Відкинути" }));

    expect(screen.getByText("Режим перегляду")).toBeInTheDocument();
    expect(screen.queryByText("Незбережені зміни")).not.toBeInTheDocument();
  });
});
