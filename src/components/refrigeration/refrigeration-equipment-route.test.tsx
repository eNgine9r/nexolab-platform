import type { ReactNode } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { refrigerationEquipment } from "@/data/refrigeration";
import type { RefrigerationEquipmentRuntime } from "@/features/refrigeration/equipment-repository-runtime";
import type { RefrigerationStructuralSnapshot } from "@/features/refrigeration/structural-snapshot-repository";

import { RefrigerationEquipmentRoute } from "./refrigeration-equipment-route";

const equipment = refrigerationEquipment[0];
const mockedRuntime = vi.hoisted(() => ({
  current: null as unknown,
}));

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

vi.mock("@/components/refrigeration/refrigeration-detail-screen", () => ({
  RefrigerationDetailScreen: ({
    equipment: loadedEquipment,
    initialSnapshot,
  }: {
    equipment: { name: string };
    initialSnapshot: RefrigerationStructuralSnapshot | null;
  }) => (
    <div data-testid="refrigeration-detail">
      <span>{loadedEquipment.name}</span>
      <span>{initialSnapshot ? "snapshot-ready" : "equipment-only"}</span>
    </div>
  ),
}));

vi.mock("@/features/refrigeration/equipment-repository-runtime", () => ({
  createRefrigerationEquipmentRuntime: () => mockedRuntime.current,
}));

function setRuntime({
  structuralGet,
  equipmentGet,
}: {
  structuralGet: ReturnType<typeof vi.fn>;
  equipmentGet: ReturnType<typeof vi.fn>;
}) {
  mockedRuntime.current = {
    mode: "live",
    repository: { get: equipmentGet },
    structuralSnapshotRepository: { get: structuralGet },
    error: null,
  } as unknown as RefrigerationEquipmentRuntime;
}

function snapshot(): RefrigerationStructuralSnapshot {
  return { equipment } as unknown as RefrigerationStructuralSnapshot;
}

beforeEach(() => {
  mockedRuntime.current = null;
});

describe("RefrigerationEquipmentRoute structural-first loading", () => {
  it("renders a structural snapshot without starting the redundant equipment read", async () => {
    const equipmentGet = vi.fn(() => new Promise(() => undefined));
    const structuralGet = vi.fn(async () => snapshot());
    setRuntime({ structuralGet, equipmentGet });

    render(<RefrigerationEquipmentRoute equipmentId={equipment.id} initialEquipment={null} />);

    expect(await screen.findByTestId("refrigeration-detail")).toHaveTextContent(equipment.name);
    expect(screen.getByTestId("refrigeration-detail")).toHaveTextContent("snapshot-ready");
    expect(screen.queryByText("Завантаження обладнання")).not.toBeInTheDocument();
    expect(structuralGet).toHaveBeenCalledTimes(1);
    expect(equipmentGet).not.toHaveBeenCalled();
  });

  it("falls back to the equipment repository only when the structural snapshot fails", async () => {
    const structuralGet = vi.fn(async () => {
      throw new Error("Structural snapshot недоступний.");
    });
    const equipmentGet = vi.fn(async () => equipment);
    setRuntime({ structuralGet, equipmentGet });

    render(<RefrigerationEquipmentRoute equipmentId={equipment.id} initialEquipment={null} />);

    expect(await screen.findByTestId("refrigeration-detail")).toHaveTextContent(equipment.name);
    expect(screen.getByTestId("refrigeration-detail")).toHaveTextContent("equipment-only");
    expect(structuralGet).toHaveBeenCalledTimes(1);
    expect(equipmentGet).toHaveBeenCalledTimes(1);
  });

  it("shows a truthful unavailable state when structural and fallback reads both fail", async () => {
    const structuralGet = vi.fn(async () => {
      throw new Error("Structural snapshot недоступний.");
    });
    const equipmentGet = vi.fn(async () => {
      throw new Error("Обладнання не знайдено.");
    });
    setRuntime({ structuralGet, equipmentGet });

    render(<RefrigerationEquipmentRoute equipmentId={equipment.id} initialEquipment={null} />);

    await waitFor(() => expect(screen.getByText("Обладнання недоступне")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent("Обладнання не знайдено.");
    expect(screen.queryByText("Завантаження обладнання")).not.toBeInTheDocument();
    expect(structuralGet).toHaveBeenCalledTimes(1);
    expect(equipmentGet).toHaveBeenCalledTimes(1);
  });
});
