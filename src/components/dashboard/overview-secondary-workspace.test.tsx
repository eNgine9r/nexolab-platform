import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { parseCameraInventory } from "@/features/cameras/domain";

import { OverviewSecondaryWorkspace } from "./overview-secondary-workspace";

describe("OverviewSecondaryWorkspace", () => {
  it.each([{ input: [] }, { input: [null] }])("shares empty camera space", ({ input }) => {
    render(
      <OverviewSecondaryWorkspace
        sessions={<h2>Сесії</h2>}
        layouts={<h2>Схеми</h2>}
        cameraInventory={parseCameraInventory(input)}
      />,
    );

    expect(screen.queryByRole("heading", { name: "Камери" })).not.toBeInTheDocument();
    expect(screen.queryByText("Камери не налаштовані")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Сесії" }).parentElement).toHaveClass("xl:col-span-6");
    expect(screen.getByRole("heading", { name: "Схеми" }).parentElement).toHaveClass("xl:col-span-6");
  });

  it("retains configured camera destinations and honest offline or invalid states", () => {
    render(
      <OverviewSecondaryWorkspace
        sessions={<h2>Сесії</h2>}
        layouts={<h2>Схеми</h2>}
        cameraInventory={parseCameraInventory([
          { id: "camera-offline", name: "Вхід", state: "offline" },
          { id: "camera-invalid", name: "Лабораторія", endpoint: "https://public.example/stream" },
        ])}
        cameraAction={<a href="/cameras">Всі камери</a>}
      />,
    );

    expect(screen.getByRole("heading", { name: "Камери" })).toBeVisible();
    expect(screen.getByRole("link", { name: /Вхід/ })).toHaveAttribute("href", "/cameras");
    expect(screen.getByRole("link", { name: /Лабораторія/ })).toHaveAttribute("href", "/cameras");
    expect(screen.getByText("camera-offline · offline")).toBeVisible();
    expect(screen.getByText("camera-invalid · invalid")).toBeVisible();
    expect(screen.getByRole("link", { name: "Всі камери" })).toHaveAttribute("href", "/cameras");
    expect(screen.getByRole("heading", { name: "Сесії" }).parentElement).toHaveClass("xl:col-span-4");
    expect(screen.getByRole("heading", { name: "Схеми" }).parentElement).toHaveClass("xl:col-span-5");
  });
});
