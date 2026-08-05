import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LayoutCatalogItem, LayoutCatalogState } from "@/features/equipment-layouts/layout-catalog";
import type { UseEquipmentLayoutsCatalogResult } from "@/hooks/use-equipment-layouts-catalog";

import { LabMap } from "./lab-map";

const mocks = vi.hoisted(() => ({
  useCatalog: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: { children: ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/hooks/use-equipment-layouts-catalog", () => ({
  useEquipmentLayoutsCatalog: mocks.useCatalog,
}));

function catalogResult(
  overrides: Partial<UseEquipmentLayoutsCatalogResult> = {},
): UseEquipmentLayoutsCatalogResult {
  return {
    mode: "live",
    state: "ready",
    items: [],
    error: null,
    retry: vi.fn(),
    ...overrides,
  };
}

function layoutItem(
  id: string,
  code: string,
  name: string,
  layoutState: LayoutCatalogState,
): LayoutCatalogItem {
  return {
    kind: layoutState === "failed" ? "failed" : "ready",
    equipment: {
      id,
      code,
      name,
      location: `Лабораторія ${code}`,
    },
    layoutState,
  } as unknown as LayoutCatalogItem;
}

describe("LabMap", () => {
  beforeEach(() => {
    mocks.useCatalog.mockReset();
    mocks.useCatalog.mockReturnValue(catalogResult());
  });

  it("renders repository-backed layout counts and canonical navigation in live mode", () => {
    mocks.useCatalog.mockReturnValue(
      catalogResult({
        items: [
          layoutItem("eq-1", "KK1", "Кліматична камера №1", "published-current"),
          layoutItem("eq-2", "KK2", "Кліматична камера №2", "published-with-draft"),
          layoutItem("eq-3", "V-01", "Холодильна вітрина", "empty"),
          layoutItem("eq-4", "V-02", "Резервна вітрина", "failed"),
        ],
      }),
    );

    render(<LabMap mode="live" enabled organizationId="org-1" />);

    expect(screen.getByLabelText("Стан схем обладнання")).toHaveTextContent("4");
    expect(screen.getByText("Кліматична камера №1")).toBeInTheDocument();
    expect(screen.getByText("Є зміни")).toBeInTheDocument();
    expect(screen.getByText("Недоступно")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Відкрити каталог" })).toHaveAttribute(
      "href",
      "/equipment-layouts",
    );
    expect(screen.queryByText("4.2 °C")).not.toBeInTheDocument();
    expect(screen.getByText("Дані зі сховища схем, без Modbus-операцій")).toBeInTheDocument();
  });

  it("shows an explicit unavailable state and retries the existing read contract", () => {
    const retry = vi.fn();
    mocks.useCatalog.mockReturnValue(
      catalogResult({
        state: "error",
        error: "Telemetry Service недоступний.",
        retry,
      }),
    );

    render(<LabMap mode="live" enabled organizationId="org-1" />);

    expect(screen.getByText("Каталог схем недоступний")).toBeInTheDocument();
    expect(screen.getByText("Telemetry Service недоступний.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Повторити" }));
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it("does not request layouts without an active organization", () => {
    render(<LabMap mode="live" enabled organizationId={null} />);

    expect(screen.getByText("Організацію не вибрано")).toBeInTheDocument();
    expect(mocks.useCatalog).toHaveBeenCalledWith({ enabled: false, organizationId: null });
  });

  it("keeps illustrative content only in explicitly labelled demo mode", () => {
    render(<LabMap mode="demo" enabled organizationId={null} />);

    expect(screen.getByText("Demo mode")).toBeInTheDocument();
    expect(screen.getByText("Ілюстративна схема, не лабораторні дані")).toBeInTheDocument();
    expect(screen.getByLabelText("Демонстраційна схема лабораторії")).toBeInTheDocument();
    expect(mocks.useCatalog).toHaveBeenCalledWith({ enabled: false, organizationId: null });
  });
});
