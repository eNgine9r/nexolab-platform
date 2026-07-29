import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { refrigerationEquipment } from "@/data/refrigeration";
import { InMemoryRefrigerationEquipmentRepository } from "@/features/refrigeration/equipment-repository";
import type { RefrigerationEquipmentRuntime } from "@/features/refrigeration/equipment-repository-runtime";

import { RefrigerationCatalogScreen } from "./refrigeration-catalog-screen";

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: { children: ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/components/dashboard/sidebar", () => ({
  Sidebar: () => <div data-testid="sidebar" />,
}));

vi.mock("@/components/dashboard/topbar", () => ({
  Topbar: ({ title }: { title: string }) => <div>{title}</div>,
}));

function runtime(): RefrigerationEquipmentRuntime {
  return {
    mode: "demo",
    repository: new InMemoryRefrigerationEquipmentRepository(refrigerationEquipment),
    sessionClient: null,
    organizationId: null,
    error: null,
  };
}

describe("RefrigerationCatalogScreen", () => {
  it("filters equipment by search text", async () => {
    render(<RefrigerationCatalogScreen runtime={runtime()} />);

    expect(await screen.findByText("Вітрина №106-01")).toBeInTheDocument();
    expect(screen.getByText("Холодильна камера №201")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Пошук обладнання"), {
      target: { value: "Compact 900" },
    });

    expect(screen.getByText("Вітрина №107-02")).toBeInTheDocument();
    expect(screen.queryByText("Вітрина №106-01")).not.toBeInTheDocument();
    expect(screen.queryByText("Холодильна камера №201")).not.toBeInTheDocument();
  });

  it("filters equipment by operational status", async () => {
    render(<RefrigerationCatalogScreen runtime={runtime()} />);
    await screen.findByText("Вітрина №106-01");

    fireEvent.change(screen.getByLabelText("Фільтр за станом"), {
      target: { value: "warning" },
    });

    expect(screen.getByText("Вітрина №107-02")).toBeInTheDocument();
    expect(screen.queryByText("Вітрина №106-01")).not.toBeInTheDocument();
  });

  it("renders an explicit empty state when no equipment matches", async () => {
    render(<RefrigerationCatalogScreen runtime={runtime()} />);
    await screen.findByText("Вітрина №106-01");

    fireEvent.change(screen.getByPlaceholderText("Пошук обладнання"), {
      target: { value: "does-not-exist" },
    });

    expect(screen.getByText("Обладнання не знайдено")).toBeInTheDocument();
  });

  it("creates equipment from the icon-first catalog action", async () => {
    render(<RefrigerationCatalogScreen runtime={runtime()} />);
    await screen.findByText("Вітрина №106-01");

    fireEvent.click(screen.getByRole("button", { name: "Додати холодильне обладнання" }));

    fireEvent.change(screen.getByLabelText(/Назва/), { target: { value: "Вітрина №108-01" } });
    fireEvent.change(screen.getByLabelText(/Код обладнання/), {
      target: { value: "CS-P1250-2026-108-01" },
    });
    fireEvent.change(screen.getByLabelText(/Розташування/), {
      target: { value: "Лабораторія 1 · Зона C" },
    });
    fireEvent.change(screen.getByLabelText(/Виробник/), { target: { value: "NEXOLAB" } });
    fireEvent.change(screen.getByLabelText(/Модель/), { target: { value: "NX-1250" } });
    fireEvent.change(screen.getByLabelText(/Серійний номер/), { target: { value: "NX-10801" } });
    fireEvent.change(screen.getByLabelText(/Температурний клас/), {
      target: { value: "3M1 (0…+5 °C)" },
    });
    fireEvent.change(screen.getByLabelText(/Кількість датчиків/), { target: { value: "48" } });
    fireEvent.click(screen.getByRole("button", { name: "Створити" }));

    expect(await screen.findByText("Вітрина №108-01")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("додано до каталогу");
    expect(screen.getByRole("link", { name: "Відкрити Вітрина №108-01" })).toBeInTheDocument();
  });

  it("requires destructive confirmation and removes the selected equipment", async () => {
    render(<RefrigerationCatalogScreen runtime={runtime()} />);
    await screen.findByText("Вітрина №106-01");

    fireEvent.click(screen.getByRole("button", { name: "Видалити Вітрина №106-01" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("Історичні схеми та аудит залишаться збереженими");

    fireEvent.click(screen.getByRole("button", { name: "Видалити" }));

    await waitFor(() => expect(screen.queryByText("Вітрина №106-01")).not.toBeInTheDocument());
    expect(screen.getByRole("status")).toHaveTextContent("видалено з каталогу");
  });
});
