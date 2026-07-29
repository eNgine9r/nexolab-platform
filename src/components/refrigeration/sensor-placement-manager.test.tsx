import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AvailableSensor } from "@/features/refrigeration/equipment-lifecycle-repository";
import type { StagedSensorConfiguration } from "@/features/refrigeration/sensor-configuration";

import { SensorPlacementManager } from "./sensor-placement-manager";

const channels: AvailableSensor[] = [
  {
    channelId: "kk2-temperature-01",
    metric: "temperature",
    unit: "degC",
    latestValue: 2.4,
    quality: "valid",
    capturedAt: "2026-07-29T12:00:00.000Z",
    isBound: false,
    boundEquipmentId: null,
    boundSlotKey: null,
  },
  {
    channelId: "kk2-temperature-02",
    metric: "temperature",
    unit: "degC",
    latestValue: 2.8,
    quality: "valid",
    capturedAt: "2026-07-29T12:00:00.000Z",
    isBound: false,
    boundEquipmentId: null,
    boundSlotKey: null,
  },
];

const configured: StagedSensorConfiguration = {
  id: "kk2-temperature-01",
  slotKey: "front-01",
  label: "01F",
  name: "temperature · kk2-temperature-01",
  side: "front",
  shelf: 1,
  position: 1,
  x: 0.14,
  y: 0.21,
  temperatureC: 2.4,
  status: "normal",
  updatedAt: "2026-07-29T12:00:00.000Z",
  trend: [2.4],
  metric: "temperature",
  unit: "degC",
};

function renderManager({
  configuration = [],
  editingSensorId = null,
}: {
  configuration?: StagedSensorConfiguration[];
  editingSensorId?: string | null;
} = {}) {
  const onConfigurationChange = vi.fn();
  const onEditingSensorIdChange = vi.fn();
  const onSelect = vi.fn();
  render(
    <SensorPlacementManager
      equipmentId="showcase-kk2"
      totalSlots={48}
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

describe("SensorPlacementManager", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("stages an unused climate-chamber channel without persisting it", () => {
    const { onConfigurationChange, onEditingSensorIdChange, onSelect } = renderManager();

    expect(screen.getByRole("option", { name: /kk2-temperature-01/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /kk2-temperature-02/ })).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Додати вибраний датчик на підкладку" }),
    );

    expect(onConfigurationChange).toHaveBeenCalledTimes(1);
    expect(onConfigurationChange.mock.calls[0]?.[0]).toEqual([
      expect.objectContaining({
        id: "kk2-temperature-01",
        slotKey: "front-01",
        side: "front",
        shelf: 1,
        position: 1,
      }),
    ]);
    expect(onSelect).toHaveBeenCalledWith("kk2-temperature-01");
    expect(onEditingSensorIdChange).toHaveBeenCalledWith("kk2-temperature-01");
  });

  it("hides used channels and stages replacement through the editor", () => {
    const { onConfigurationChange } = renderManager({
      configuration: [configured],
      editingSensorId: configured.id,
    });

    const addSelector = screen.getByRole("combobox", {
      name: "Доступний датчик кліматичної камери",
    });
    expect(addSelector).not.toHaveTextContent("kk2-temperature-01");
    expect(addSelector).toHaveTextContent("kk2-temperature-02");

    fireEvent.change(screen.getByRole("combobox", { name: "Замінити канал датчика" }), {
      target: { value: "kk2-temperature-02" },
    });

    expect(onConfigurationChange).toHaveBeenCalledWith([
      expect.objectContaining({
        id: "kk2-temperature-02",
        slotKey: "front-01",
        label: "01F",
      }),
    ]);
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

    fireEvent.click(
      screen.getByRole("button", { name: "Видалити датчик з підкладки" }),
    );
    expect(onConfigurationChange).toHaveBeenLastCalledWith([]);
    expect(onEditingSensorIdChange).toHaveBeenCalledWith(null);
  });
});
