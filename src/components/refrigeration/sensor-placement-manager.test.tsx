import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { refrigerationEquipment } from "@/data/refrigeration";
import type { AvailableSensor } from "@/features/refrigeration/equipment-lifecycle-repository";
import type { StagedSensorConfiguration } from "@/features/refrigeration/sensor-configuration";

import { SensorPlacementManager } from "./sensor-placement-manager";

const equipmentFixture = refrigerationEquipment[0];
if (!equipmentFixture) throw new Error("Refrigeration equipment fixture is required.");
const equipment = {
  ...equipmentFixture,
  id: "showcase-kk2",
  name: "Showcase KK2",
  transportNodeId: "edge-01",
  totalSensors: 48,
};

const channels: AvailableSensor[] = [
  {
    channelId: "106-03",
    metric: "temperature",
    unit: "degC",
    latestValue: 24,
    quality: "valid",
    capturedAt: new Date().toISOString(),
    isBound: false,
    boundEquipmentId: null,
    boundSlotKey: null,
  },
  {
    channelId: "106-04",
    metric: "temperature",
    unit: "degC",
    latestValue: null,
    quality: "no-data",
    capturedAt: "2026-07-29T12:00:00.000Z",
    isBound: false,
    boundEquipmentId: null,
    boundSlotKey: null,
  },
  {
    channelId: "107-01",
    metric: "temperature",
    unit: "degC",
    latestValue: null,
    quality: "planned",
    capturedAt: "2026-07-29T12:00:00.000Z",
    isBound: true,
    boundEquipmentId: "showcase-other",
    boundSlotKey: "front-02",
  },
];

const configured: StagedSensorConfiguration = {
  id: "106-03",
  slotKey: "front-01",
  label: "01F",
  name: "temperature · 106-03",
  side: "front",
  shelf: 1,
  position: 1,
  x: 0.14,
  y: 0.21,
  temperatureC: 24,
  status: "normal",
  updatedAt: new Date().toISOString(),
  trend: [24],
  metric: "temperature",
  unit: "degC",
};

function renderManager({
  configuration = [],
  editingSensorId = null,
  pendingChannelId = null,
  totalSlots = 48,
  organizationId = "org-equipment-map",
}: {
  configuration?: StagedSensorConfiguration[];
  editingSensorId?: string | null;
  pendingChannelId?: string | null;
  totalSlots?: number;
  organizationId?: string | null;
} = {}) {
  const onConfigurationChange = vi.fn();
  const onEditingSensorIdChange = vi.fn();
  const onPendingChannelChange = vi.fn();
  const onSelect = vi.fn();
  render(
    <SensorPlacementManager
      equipment={equipment}
      organizationId={organizationId}
      totalSlots={totalSlots}
      channels={channels}
      configuration={configuration}
      editingSensorId={editingSensorId}
      pendingChannelId={pendingChannelId}
      onEditingSensorIdChange={onEditingSensorIdChange}
      onPendingChannelChange={onPendingChannelChange}
      onConfigurationChange={onConfigurationChange}
      onSelect={onSelect}
    />,
  );
  return { onConfigurationChange, onEditingSensorIdChange, onPendingChannelChange, onSelect };
}

function openAddSelector() {
  fireEvent.click(screen.getByRole("button", { name: "Додати датчик" }));
  return screen.getByTestId("equipment-map-quick-sensor-picker");
}

function chooseQuickPoint(selector: HTMLElement, channelId: string) {
  const search = within(selector).getByRole("searchbox", { name: "Пошук датчика" });
  fireEvent.change(search, { target: { value: channelId } });
  fireEvent.click(within(selector).getByRole("button", { name: new RegExp(`канал ${channelId}`) }));
}

function chooseReplacementPoint(selector: HTMLElement, channelId: string) {
  const search = within(selector).getByRole("searchbox", { name: "Пошук" });
  fireEvent.change(search, { target: { value: channelId } });
  fireEvent.click(within(selector).getByRole("treeitem", { name: new RegExp(channelId) }));
}

describe("SensorPlacementManager", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("selects a no-data channel in one click without mutating configuration", () => {
    const { onConfigurationChange, onPendingChannelChange } = renderManager();
    const selector = openAddSelector();
    const search = within(selector).getByRole("searchbox", { name: "Пошук датчика" });
    expect(search).toHaveFocus();
    chooseQuickPoint(selector, "106-04");

    expect(search).toHaveValue("");
    expect(onPendingChannelChange).toHaveBeenLastCalledWith("106-04");
    expect(onConfigurationChange).not.toHaveBeenCalled();
    fireEvent.click(within(selector).getByRole("button", { name: "Закрити" }));
    expect(onPendingChannelChange).toHaveBeenLastCalledWith(null);
    expect(screen.queryByTestId("equipment-map-quick-sensor-picker")).not.toBeInTheDocument();
  });

  it("keeps quick add available without organization context while advanced replacement stays fail-closed", () => {
    const { onPendingChannelChange } = renderManager({
      configuration: [configured],
      editingSensorId: configured.id,
      organizationId: null,
    });

    expect(screen.getByRole("button", { name: "Додати датчик" })).toBeEnabled();
    chooseQuickPoint(openAddSelector(), "106-04");
    expect(onPendingChannelChange).toHaveBeenLastCalledWith("106-04");

    fireEvent.click(screen.getByText("Додаткові параметри"));
    expect(screen.getByRole("button", { name: "Вибрати інший канал вимірювання" })).toBeDisabled();
    expect(screen.getByText(/Контекст організації недоступний/)).toBeInTheDocument();
  });

  it("recovers a legacy zero-capacity passport as a 48-slot layout", () => {
    const { onPendingChannelChange } = renderManager({ totalSlots: 0 });
    expect(screen.getByText("0/48")).toBeInTheDocument();
    expect(screen.getByText(/місткість датчиків була задана як 0/)).toBeInTheDocument();
    chooseQuickPoint(openAddSelector(), "106-03");
    expect(onPendingChannelChange).toHaveBeenLastCalledWith("106-03");
  });
  it("keeps foreign-bound channels visible as conflicts but outside quick selection", () => {
    renderManager();
    expect(screen.getByText(/Недоступні через активну прив’язку: 107-01/)).toBeInTheDocument();
    const selector = openAddSelector();
    const search = within(selector).getByRole("searchbox", { name: "Пошук датчика" });
    fireEvent.change(search, { target: { value: "107-01" } });
    expect(within(selector).getByText("Доступних датчиків не знайдено.")).toBeInTheDocument();
  });

  it("keeps configured channels out of Add and preserves explicit replacement", () => {
    const { onConfigurationChange } = renderManager({
      configuration: [configured],
      editingSensorId: configured.id,
    });
    const addSelector = openAddSelector();
    const addSearch = within(addSelector).getByRole("searchbox", { name: "Пошук датчика" });
    fireEvent.change(addSearch, { target: { value: "106-03" } });
    expect(within(addSelector).getByText("Доступних датчиків не знайдено.")).toBeInTheDocument();
    fireEvent.click(within(addSelector).getByRole("button", { name: "Закрити" }));

    fireEvent.click(screen.getByText("Додаткові параметри"));
    fireEvent.click(screen.getByRole("button", { name: "Вибрати інший канал вимірювання" }));
    const selector = screen.getByTestId("equipment-map-replace-telemetry-selector");
    chooseReplacementPoint(selector, "106-04");
    expect(onConfigurationChange).not.toHaveBeenCalled();
    fireEvent.click(within(selector).getByRole("button", { name: "Підтвердити вибір" }));
    expect(onConfigurationChange).toHaveBeenCalledWith([
      expect.objectContaining({ id: "106-04", slotKey: "front-01", label: "01F" }),
    ]);
  });
  it("treats confirming the current replacement channel as a no-op", () => {
    const { onConfigurationChange } = renderManager({
      configuration: [configured],
      editingSensorId: configured.id,
    });
    fireEvent.click(screen.getByText("Додаткові параметри"));
    fireEvent.click(screen.getByRole("button", { name: "Вибрати інший канал вимірювання" }));
    const selector = screen.getByTestId("equipment-map-replace-telemetry-selector");
    chooseReplacementPoint(selector, "106-03");
    fireEvent.click(within(selector).getByRole("button", { name: "Підтвердити вибір" }));
    expect(onConfigurationChange).not.toHaveBeenCalled();
    expect(screen.queryByTestId("equipment-map-replace-telemetry-selector")).not.toBeInTheDocument();
  });

  it("commits inline rename with Enter, cancels with Escape, and keeps remove advanced", () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { onConfigurationChange, onEditingSensorIdChange } = renderManager({
      configuration: [configured],
      editingSensorId: configured.id,
    });

    fireEvent.click(screen.getByRole("button", { name: "Перейменувати маркер 01F" }));
    const rename = screen.getByRole("textbox", { name: "Нова назва маркера" });
    fireEvent.change(rename, { target: { value: "Тест-пакет 01" } });
    fireEvent.keyDown(rename, { key: "Enter" });
    expect(onConfigurationChange).toHaveBeenCalledWith([
      expect.objectContaining({ id: configured.id, label: "Тест-пакет 01" }),
    ]);

    fireEvent.click(screen.getByText("Додаткові параметри"));
    fireEvent.click(screen.getByRole("button", { name: "Видалити датчик з підкладки" }));
    expect(onConfigurationChange).toHaveBeenLastCalledWith([]);
    expect(onEditingSensorIdChange).toHaveBeenCalledWith(null);
  });
});
