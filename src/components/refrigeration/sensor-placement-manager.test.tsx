import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AvailableSensor } from "@/features/refrigeration/equipment-lifecycle-repository";
import type { StagedSensorConfiguration } from "@/features/refrigeration/sensor-configuration";

import { SensorPlacementManager } from "./sensor-placement-manager";

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
    quality: "no-data",
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
      equipmentId="showcase-kk2"
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

describe("SensorPlacementManager", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("shows live and no-data KK2 channels and stages an active channel", () => {
    const { onConfigurationChange, onEditingSensorIdChange, onSelect } = renderManager();

    expect(screen.getByRole("option", { name: /106-03.*Live/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /106-04.*Немає даних/ })).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Додати вибраний датчик на підкладку" }),
    );

    expect(onConfigurationChange).toHaveBeenCalledTimes(1);
    expect(onConfigurationChange.mock.calls[0]?.[0]).toEqual([
      expect.objectContaining({
        id: "106-03",
        slotKey: "front-01",
        side: "front",
        shelf: 1,
        position: 1,
      }),
    ]);
    expect(onSelect).toHaveBeenCalledWith("106-03");
    expect(onEditingSensorIdChange).toHaveBeenCalledWith("106-03");
  });

  it("recovers a legacy zero-capacity passport as a 48-slot layout", () => {
    const { onConfigurationChange } = renderManager({ totalSlots: 0 });

    expect(screen.getByText("0/48")).toBeInTheDocument();
    expect(screen.getByText(/місткість датчиків була задана як 0/)).toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: "Доступний датчик кліматичної камери" }),
    ).toBeEnabled();

    fireEvent.change(
      screen.getByRole("combobox", { name: "Доступний датчик кліматичної камери" }),
      { target: { value: "106-04" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Додати вибраний датчик на підкладку" }),
    );

    expect(onConfigurationChange).toHaveBeenCalledWith([
      expect.objectContaining({ id: "106-04", slotKey: "front-01" }),
    ]);
  });

  it("allows a configured channel without telemetry to be placed", () => {
    const { onConfigurationChange } = renderManager();
    fireEvent.change(
      screen.getByRole("combobox", { name: "Доступний датчик кліматичної камери" }),
      { target: { value: "106-04" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Додати вибраний датчик на підкладку" }),
    );

    expect(onConfigurationChange).toHaveBeenCalledWith([
      expect.objectContaining({
        id: "106-04",
        temperatureC: null,
        status: "no-data",
      }),
    ]);
  });

  it("keeps a foreign-bound channel visible but disables conflicting placement", () => {
    renderManager();

    const option = screen.getByRole("option", { name: /107-01.*уже розміщений/ });
    expect(option).toBeDisabled();
    expect(option).toHaveTextContent("showcase-other");
  });

  it("hides the current channel and stages replacement through the editor", () => {
    const { onConfigurationChange } = renderManager({
      configuration: [configured],
      editingSensorId: configured.id,
    });

    const addSelector = screen.getByRole("combobox", {
      name: "Доступний датчик кліматичної камери",
    });
    expect(addSelector).not.toHaveTextContent("106-03");
    expect(addSelector).toHaveTextContent("106-04");

    fireEvent.change(screen.getByRole("combobox", { name: "Замінити канал датчика" }), {
      target: { value: "106-04" },
    });

    expect(onConfigurationChange).toHaveBeenCalledWith([
      expect.objectContaining({
        id: "106-04",
        slotKey: "front-01",
        label: "01F",
        status: "no-data",
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
