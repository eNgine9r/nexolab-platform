import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { normalizeEquipmentRegistry, type EquipmentRegistryAsset } from "@/features/equipment/asset-registry";
import { getRefrigerationEquipment } from "@/data/refrigeration";
import type {
  ClimateCatalogRepository,
  MeasurementDevice,
} from "@/features/refrigeration/climate-catalog-repository";
import type { RefrigerationEquipmentRepository } from "@/features/refrigeration/equipment-repository";

import { EquipmentAssetDetails } from "./equipment-asset-details";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a>,
}));

const asset: EquipmentRegistryAsset = {
  key: "measurement-device:device-1",
  id: "device-1",
  category: "energy-meter",
  primaryIdentifier: "meter:12",
  displayName: "Лічильник 1",
  manufacturer: "TOMZN",
  model: "DDS238-2",
  serialNumber: null,
  chamberId: "chamber-1",
  chamberLabel: "KK1 · Камера 1",
  locationLabel: "Камера 1",
  lifecycleStatus: null,
  healthStatus: null,
  connectionStatus: "connected",
  catalogStatus: "active",
  calibrationStatus: "not-applicable",
  statusKeys: ["connected", "active"],
  canonicalHref: null,
  searchText: "meter 12 лічильник tomzn",
  chamber: {
    id: "chamber-1",
    code: "KK1",
    nodeId: "chamber-1",
    transportNodeId: "edge-01",
    busId: "bus-1",
    busKey: "rs485-main",
    name: "Камера 1",
    displayOrder: 1,
    status: "active",
    version: 1,
    createdAt: "2026-08-01T00:00:00Z",
    updatedAt: "2026-08-01T00:00:00Z",
  },
  source: {
    id: "device-1",
    businessKey: "meter:12",
    deviceType: "energy_meter",
    manufacturer: "TOMZN",
    model: "DDS238-2",
    unitId: 12,
    displayName: "Лічильник 1",
    designation: "W1",
    connectionStatus: "connected",
    status: "active",
    measuredParameters: [{ metric: "energy.total", unit: "kWh" }],
    version: 2,
  },
};

function climateRepository(): ClimateCatalogRepository {
  return {
    listChambers: vi.fn(),
    getEquipment: vi.fn(),
    updateMeasurementDevice: vi.fn(async (_chamber, _device, input): Promise<MeasurementDevice> => ({
      id: "device-1",
      businessKey: "meter:12",
      deviceType: "energy_meter",
      manufacturer: input.manufacturer,
      model: input.model,
      unitId: 12,
      displayName: input.displayName,
      designation: input.designation,
      connectionStatus: "connected",
      status: "active",
      measuredParameters: [{ metric: "energy.total", unit: "kWh" }],
      version: 3,
    })),
    updatePhysicalSensor: vi.fn(),
  };
}

function renderDetails(canManage: boolean, repository = climateRepository()) {
  const onSaved = vi.fn();
  const onClose = vi.fn();
  render(
    <EquipmentAssetDetails
      asset={asset}
      canManage={canManage}
      equipmentRepository={null}
      climateCatalogRepository={repository}
      onSaved={onSaved}
      onClose={onClose}
    />,
  );
  return { repository, onSaved, onClose };
}

describe("EquipmentAssetDetails metadata editing", () => {
  it("does not expose an effective edit action without equipment.manage", () => {
    renderDetails(false);
    expect(screen.queryByRole("button", { name: "Редагувати метадані" })).not.toBeInTheDocument();
    expect(screen.getByText("Доступ лише для перегляду.")).toBeInTheDocument();
  });

  it("keeps transport identity read-only and requires explicit discard for dirty edits", () => {
    const { onClose } = renderDetails(true);
    fireEvent.click(screen.getByRole("button", { name: "Редагувати метадані" }));

    expect(
      screen.getByText(/Modbus Unit ID 12 і transport identity залишаються read-only/),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/Modbus Unit ID/i)).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Назва"), { target: { value: "Новий лічильник" } });
    fireEvent.click(screen.getByRole("button", { name: "Закрити паспорт обладнання" }));

    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByText("Є незбережені зміни")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Продовжити редагування" }));
    expect(screen.getByDisplayValue("Новий лічильник")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Скасувати" }));
    fireEvent.click(screen.getByRole("button", { name: "Відкинути зміни" }));
    expect(screen.queryByLabelText("Назва")).not.toBeInTheDocument();
  });

  it("saves only canonical administrative metadata and refreshes the registry", async () => {
    const repository = climateRepository();
    const { onSaved } = renderDetails(true, repository);
    fireEvent.click(screen.getByRole("button", { name: "Редагувати метадані" }));
    fireEvent.change(screen.getByLabelText("Назва"), { target: { value: "Лічильник випробувальний" } });
    fireEvent.click(screen.getByRole("button", { name: "Зберегти" }));

    await waitFor(() => expect(repository.updateMeasurementDevice).toHaveBeenCalledTimes(1));
    expect(repository.updateMeasurementDevice).toHaveBeenCalledWith(
      "chamber-1",
      "device-1",
      {
        displayName: "Лічильник випробувальний",
        designation: "W1",
        manufacturer: "TOMZN",
        model: "DDS238-2",
      },
      2,
    );
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(screen.queryByLabelText("Назва")).not.toBeInTheDocument();
  });

  it("reuses the canonical refrigeration mutation while preserving chamber identity and lifecycle", async () => {
    const source = getRefrigerationEquipment("showcase-106-01");
    if (!source) throw new Error("Reference refrigeration fixture is missing");
    const refrigerationAsset = normalizeEquipmentRegistry([source], [], [])[0];
    if (!refrigerationAsset || refrigerationAsset.category !== "refrigeration-equipment") {
      throw new Error("Reference refrigeration registry asset is missing");
    }
    const update = vi.fn<RefrigerationEquipmentRepository["update"]>(async () => ({
      ...source,
      name: "Вітрина випробувальна",
      version: 2,
    }));
    const repository: RefrigerationEquipmentRepository = {
      list: vi.fn(async () => [source]),
      get: vi.fn(async () => source),
      create: vi.fn(),
      update,
      remove: vi.fn(),
    };
    const onSaved = vi.fn();
    render(
      <EquipmentAssetDetails
        asset={refrigerationAsset}
        canManage
        equipmentRepository={repository}
        climateCatalogRepository={null}
        onSaved={onSaved}
        onClose={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Редагувати метадані" }));
    fireEvent.change(screen.getByLabelText("Назва"), { target: { value: "Вітрина випробувальна" } });
    fireEvent.click(screen.getByRole("button", { name: "Зберегти" }));

    await waitFor(() => expect(update).toHaveBeenCalledTimes(1));
    const [, input, expectedVersion] = update.mock.calls[0]!;
    expect(expectedVersion).toBe(source.version);
    expect(input).toMatchObject({
      code: source.code,
      climateChamberId: source.climateChamberId ?? undefined,
      nodeId: source.nodeId,
      lifecycleStatus: source.lifecycleStatus,
      totalSensors: source.totalSensors,
      name: "Вітрина випробувальна",
    });
    expect(onSaved).toHaveBeenCalledTimes(1);
  });
});
