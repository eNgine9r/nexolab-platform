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
  totalSlots = 48,
}: {
  configuration?: StagedSensorConfiguration[];
  editingSensorId?: string | null;
  totalSlots?: number;
} = {}) {
  const onConfigurationChange = vi.fn();
  const onEditingSensorIdChange = vi.fn();
  const onSelect = vi.fn();
  render(
    <SensorPlacementManager
      equipment={equipment}
      organizationId="org-equipment-map"
      totalSlots={totalSlots}
      channels={channels}
      configuration={configuration}
      editingSensorId={editingSensorId}
      onEditingSensorIdChange={onEditingSensorIdChange}
      onConfigurationChange={onConfigurationChange}
      onSelect={onSelect}
    />,
  );
  return { onConfigurationChange, onEditingSensorIdChange, onSelect };
}

function openAddSelector() {
  fireEvent.click(screen.getByRole("button", { name: "Вибрати датчик або прилад для додавання" }));
  return screen.getByTestId("equipment-map-add-telemetry-selector");
}

function choosePoint(selector: HTMLElement, channelId: string) {
  const search = within(selector).getByRole("searchbox", { name: "Пошук" });
  fireEvent.change(search, { target: { value: channelId } });
  fireEvent.click(within(selector).getByRole("treeitem", { name: new RegExp(channelId) }));
}

describe("SensorPlacementManager", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("keeps no-data channels eligible and mutates staged configuration only after Confirm", () => {
    const { onConfigurationChange, onEditingSensorIdChange, onSelect } = renderManager();

    const selector = openAddSelector();
    choosePoint(selector, "106-04");
    expect(within(selector).getByTestId("telemetry-selection-count")).toHaveTextContent("1 / 1");
    expect(onConfigurationChange).not.toHaveBeenCalled();

    fireEvent.click(within(selector).getByRole("button", { name: "Скасувати" }));
    expect(onConfigurationChange).not.toHaveBeenCalled();
    expect(screen.queryByTestId("equipment-map-add-telemetry-selector")).not.toBeInTheDocument();

    const confirmedSelector = openAddSelector();
    choosePoint(confirmedSelector, "106-04");
    fireEvent.click(within(confirmedSelector).getByRole("button", { name: "Підтвердити вибір" }));

    expect(onConfigurationChange).toHaveBeenCalledTimes(1);
    expect(onConfigurationChange.mock.calls[0]?.[0]).toEqual([
      expect.objectContaining({
        id: "106-04",
        slotKey: "front-01",
        side: "front",
        shelf: 1,
        position: 1,
        temperatureC: null,
        status: "no-data",
      }),
    ]);
    expect(onSelect).toHaveBeenCalledWith("106-04");
    expect(onEditingSensorIdChange).toHaveBeenCalledWith("106-04");
  });

  it("recovers a legacy zero-capacity passport as a 48-slot layout", () => {
    const { onConfigurationChange } = renderManager({ totalSlots: 0 });

    expect(screen.getByText("0/48")).toBeInTheDocument();
    expect(screen.getByText(/місткість датчиків була задана як 0/)).toBeInTheDocument();

    const selector = openAddSelector();
    choosePoint(selector, "106-03");
    fireEvent.click(within(selector).getByRole("button", { name: "Підтвердити вибір" }));

    expect(onConfigurationChange).toHaveBeenCalledWith([
      expect.objectContaining({ id: "106-03", slotKey: "front-01" }),
    ]);
  });

  it("keeps foreign-bound channels visible as conflicts but outside the selectable tree", () => {
    renderManager();

    expect(screen.getByText(/Недоступні через активну прив’язку: 107-01/)).toBeInTheDocument();
    const selector = openAddSelector();
    const search = within(selector).getByRole("searchbox", { name: "Пошук" });
    fireEvent.change(search, { target: { value: "107-01" } });
    expect(within(selector).getByText("Точок телеметрії не знайдено")).toBeInTheDocument();
  });

  it("does not offer an already configured channel in Add and confirms replacement explicitly", () => {
    const { onConfigurationChange } = renderManager({
      configuration: [configured],
      editingSensorId: configured.id,
    });

    const addSelector = openAddSelector();
    const addSearch = within(addSelector).getByRole("searchbox", { name: "Пошук" });
    fireEvent.change(addSearch, { target: { value: "106-03" } });
    expect(within(addSelector).getByText("Точок телеметрії не знайдено")).toBeInTheDocument();
    fireEvent.click(within(addSelector).getByRole("button", { name: "Скасувати" }));

    expect(screen.getByRole("button", { name: "Вибрати інший канал вимірювання" })).toHaveTextContent(
      "106-03 · temperature · degC",
    );
    fireEvent.click(screen.getByRole("button", { name: "Вибрати інший канал вимірювання" }));
    const replaceSelector = screen.getByTestId("equipment-map-replace-telemetry-selector");
    choosePoint(replaceSelector, "106-04");
    expect(onConfigurationChange).not.toHaveBeenCalled();

    fireEvent.click(within(replaceSelector).getByRole("button", { name: "Скасувати" }));
    expect(onConfigurationChange).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Вибрати інший канал вимірювання" }));
    const confirmedSelector = screen.getByTestId("equipment-map-replace-telemetry-selector");
    choosePoint(confirmedSelector, "106-04");
    fireEvent.click(within(confirmedSelector).getByRole("button", { name: "Підтвердити вибір" }));

    expect(onConfigurationChange).toHaveBeenCalledWith([
      expect.objectContaining({
        id: "106-04",
        slotKey: "front-01",
        label: "01F",
        status: "no-data",
      }),
    ]);
  });

  it("treats confirming the current replacement channel as a no-op", () => {
    const { onConfigurationChange } = renderManager({
      configuration: [configured],
      editingSensorId: configured.id,
    });

    fireEvent.click(screen.getByRole("button", { name: "Вибрати інший канал вимірювання" }));
    const selector = screen.getByTestId("equipment-map-replace-telemetry-selector");
    choosePoint(selector, "106-03");
    fireEvent.click(within(selector).getByRole("button", { name: "Підтвердити вибір" }));

    expect(onConfigurationChange).not.toHaveBeenCalled();
    expect(screen.queryByTestId("equipment-map-replace-telemetry-selector")).not.toBeInTheDocument();
  });

  it("stages marker parameter edits and removal only through edit controls", () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { onConfigurationChange, onEditingSensorIdChange } = renderManager({
      configuration: [configured],
      editingSensorId: configured.id,
    });

    fireEvent.change(screen.getByRole("textbox", { name: "Підпис датчика" }), {
      target: { value: "Тест-пакет 01" },
    });
    expect(onConfigurationChange).toHaveBeenCalledWith([
      expect.objectContaining({ id: configured.id, label: "Тест-пакет 01" }),
    ]);

    fireEvent.click(screen.getByRole("button", { name: "Видалити датчик з підкладки" }));
    expect(onConfigurationChange).toHaveBeenLastCalledWith([]);
    expect(onEditingSensorIdChange).toHaveBeenCalledWith(null);
  });
});
