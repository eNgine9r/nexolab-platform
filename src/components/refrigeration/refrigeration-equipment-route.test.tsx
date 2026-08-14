import type { ReactNode } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { refrigerationEquipment } from "@/data/refrigeration";
import type { RefrigerationEquipmentRepository } from "@/features/refrigeration/equipment-repository";
import type { RefrigerationEquipmentRuntime } from "@/features/refrigeration/equipment-repository-runtime";
import type {
  RefrigerationStructuralSnapshot,
  RefrigerationStructuralSnapshotRepository,
} from "@/features/refrigeration/structural-snapshot-repository";

import { RefrigerationEquipmentRoute } from "./refrigeration-equipment-route";

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
    equipment,
    initialSnapshot,
  }: {
    equipment: { name: string };
    initialSnapshot: RefrigerationStructuralSnapshot | null;
  }) => (
    <div data-testid="refrigeration-detail">
      <span>{equipment.name}</span>
      <span>{initialSnapshot ? "snapshot-ready" : "equipment-only"}</span>
    </div>
  ),
}));

vi.mock("@/features/refrigeration/equipment-repository-runtime", () => ({
  createRefrigerationEquipmentRuntime: () => mockedRuntime.current,
}));

function runtime(options: {
  equipmentRepository: RefrigerationEquipmentRepository | null;
  structuralRepository: RefrigerationStructuralSnapshotRepository | null;
}): RefrigerationEquipmentRuntime {
  return {
    mode: "live",
    repository: options.equipmentRepository,
    equipmentRepository: options.equipmentRepository,
    lifecycleRepository: null,
    structuralSnapshotRepository: options.structuralRepository,
    sensorConfigurationRepository: null,
    climateCatalogRepository: null,
    sessionClient: null,
    organizationId: "00000000-0000-0000-0000-000000000001",
    error: null,
  };
}

function equipmentRepository(
  get: RefrigerationEquipmentRepository["get"],
): RefrigerationEquipmentRepository {
  return {
    get,
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  } as unknown as RefrigerationEquipmentRepository;
}

function structuralRepository(
  get: RefrigerationStructuralSnapshotRepository["get"],
): RefrigerationStructuralSnapshotRepository {
  return {
    get,
    invalidate: vi.fn(),
    clear: vi.fn(),
  };
}

function snapshot(): RefrigerationStructuralSnapshot {
  return {
    equipment: refrigerationEquipment[0],
    activeImage: null,
    layout: {
      id: "layout-1",
      equipmentId: refrigerationEquipment[0].id,
      version: 1,
      etag: 'W/"1"',
      imageId: null,
      image: null,
      placements: [],
      createdAt: "2026-08-14T07:00:00.000Z",
      updatedAt: "2026-08-14T07:00:00.000Z",
    },
    layoutRevision: 1,
    placementsCount: 0,
    bindings: [],
    channels: [],
    generatedAt: "2026-08-14T07:00:00.000Z",
  };
}

beforeEach(() => {
  mockedRuntime.current = null;
});

describe("RefrigerationEquipmentRoute structural-first loading", () => {
  it("renders a structural snapshot without starting the redundant equipment read", async () => {
    const legacyGet = vi.fn<RefrigerationEquipmentRepository["get"]>(
      () => new Promise(() => undefined),
    );
    const structuralGet = vi.fn<RefrigerationStructuralSnapshotRepository["get"]>(async () =>
      snapshot(),
    );
    mockedRuntime.current = runtime({
      equipmentRepository: equipmentRepository(legacyGet),
      structuralRepository: structuralRepository(structuralGet),
    });

    render(
      <RefrigerationEquipmentRoute
        equipmentId={refrigerationEquipment[0].id}
        initialEquipment={null}
      />,
    );

    expect(await screen.findByTestId("refrigeration-detail")).toHaveTextContent(
      refrigerationEquipment[0].name,
    );
    expect(screen.getByTestId("refrigeration-detail")).toHaveTextContent("snapshot-ready");
    expect(screen.queryByText("Завантаження обладнання")).not.toBeInTheDocument();
    expect(structuralGet).toHaveBeenCalledTimes(1);
    expect(legacyGet).not.toHaveBeenCalled();
  });

  it("falls back to the equipment repository only when the structural snapshot fails", async () => {
    const structuralGet = vi.fn<RefrigerationStructuralSnapshotRepository["get"]>(async () => {
      throw new Error("Structural snapshot недоступний.");
    });
    const legacyGet = vi.fn<RefrigerationEquipmentRepository["get"]>(
      async () => refrigerationEquipment[0],
    );
    mockedRuntime.current = runtime({
      equipmentRepository: equipmentRepository(legacyGet),
      structuralRepository: structuralRepository(structuralGet),
    });

    render(
      <RefrigerationEquipmentRoute
        equipmentId={refrigerationEquipment[0].id}
        initialEquipment={null}
      />,
    );

    expect(await screen.findByTestId("refrigeration-detail")).toHaveTextContent(
      refrigerationEquipment[0].name,
    );
    expect(screen.getByTestId("refrigeration-detail")).toHaveTextContent("equipment-only");
    expect(structuralGet).toHaveBeenCalledTimes(1);
    expect(legacyGet).toHaveBeenCalledTimes(1);
  });

  it("shows a truthful unavailable state when structural and fallback reads both fail", async () => {
    const structuralGet = vi.fn<RefrigerationStructuralSnapshotRepository["get"]>(async () => {
      throw new Error("Structural snapshot недоступний.");
    });
    const legacyGet = vi.fn<RefrigerationEquipmentRepository["get"]>(async () => {
      throw new Error("Обладнання не знайдено.");
    });
    mockedRuntime.current = runtime({
      equipmentRepository: equipmentRepository(legacyGet),
      structuralRepository: structuralRepository(structuralGet),
    });

    render(
      <RefrigerationEquipmentRoute
        equipmentId={refrigerationEquipment[0].id}
        initialEquipment={null}
      />,
    );

    await waitFor(() => expect(screen.getByText("Обладнання недоступне")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent("Обладнання не знайдено.");
    expect(screen.queryByText("Завантаження обладнання")).not.toBeInTheDocument();
    expect(structuralGet).toHaveBeenCalledTimes(1);
    expect(legacyGet).toHaveBeenCalledTimes(1);
  });
});
