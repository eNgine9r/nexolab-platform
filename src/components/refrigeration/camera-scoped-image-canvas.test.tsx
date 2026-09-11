import { createRef } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { RefrigerationSensor } from "@/data/refrigeration";
import type { AvailableSensor } from "@/features/refrigeration/equipment-lifecycle-repository";

import { CameraScopedImageCanvas } from "./camera-scoped-image-canvas";

vi.mock("next/image", () => ({
  default: ({ alt, ...props }: React.ImgHTMLAttributes<HTMLImageElement>) => (
    // eslint-disable-next-line @next/next/no-img-element
    <img alt={alt} {...props} />
  ),
}));

const sensor: RefrigerationSensor = {
  id: "106-03",
  label: "441",
  name: "temperature · 106-03",
  side: "front",
  shelf: 1,
  position: 1,
  x: 0.2,
  y: 0.3,
  temperatureC: 4.2,
  status: "normal",
  updatedAt: "2026-09-10T07:00:00.000Z",
  trend: [4.2],
};
const pending: AvailableSensor = {
  channelId: "106-04",
  inventoryNumber: "442",
  metric: "temperature",
  unit: "degC",
  latestValue: null,
  quality: "no-data",
  capturedAt: "2026-09-10T07:00:00.000Z",
  isBound: false,
  boundEquipmentId: null,
  boundSlotKey: null,
};

function renderCanvas(options: { pendingPlacement?: AvailableSensor | null } = {}) {
  const onPlaceAtPoint = vi.fn();
  const onSelect = vi.fn();
  const onEditSensor = vi.fn();
  const onMarkerPointerDown = vi.fn();
  const stageRef = createRef<HTMLDivElement>();

  render(
    <CameraScopedImageCanvas
      equipmentId="showcase-kk2"
      equipmentName="Showcase KK2"
      image={null}
      visibleSensors={[sensor]}
      placementBySensorId={new Map([[sensor.id, { sensorId: sensor.id, x: sensor.x, y: sensor.y }]])}
      selectedId={null}
      mode="edit"
      snapMode="none"
      stageRef={stageRef}
      onSelect={onSelect}
      onEditSensor={onEditSensor}
      onMarkerKeyDown={() => undefined}
      onMarkerPointerDown={onMarkerPointerDown}
      onMarkerPointerMove={() => undefined}
      onMarkerPointerUp={() => undefined}
      pendingPlacement={options.pendingPlacement === undefined ? pending : options.pendingPlacement}
      suggestedPlacement={{ x: 0.25, y: 0.35 }}
      onPlaceAtPoint={onPlaceAtPoint}
      onImageDimensions={() => undefined}
    />,
  );

  const stage = screen.getByTestId("equipment-image-stage");
  stage.getBoundingClientRect = () =>
    ({
      x: 100,
      y: 50,
      left: 100,
      top: 50,
      right: 900,
      bottom: 650,
      width: 800,
      height: 600,
      toJSON: () => undefined,
    }) as DOMRect;
  return { stage, onPlaceAtPoint, onSelect, onEditSensor, onMarkerPointerDown };
}
describe("CameraScopedImageCanvas placement mode", () => {
  it("places the pending channel only after a completed tap", () => {
    const { stage, onPlaceAtPoint } = renderCanvas();

    expect(stage).toHaveAttribute("data-placement-mode", "active");
    expect(screen.getByText(/№ 442 · натисніть на фото/)).toBeInTheDocument();
    const photoSurface = screen.getByText("Фото Showcase KK2 не завантажено");

    fireEvent.pointerDown(photoSurface, {
      pointerId: 3,
      button: 0,
      clientX: 500,
      clientY: 350,
    });
    expect(onPlaceAtPoint).not.toHaveBeenCalled();
    fireEvent.pointerUp(photoSurface, {
      pointerId: 3,
      button: 0,
      clientX: 500,
      clientY: 350,
    });

    expect(onPlaceAtPoint).toHaveBeenCalledTimes(1);
    expect(onPlaceAtPoint).toHaveBeenCalledWith({ x: 0.5, y: 0.5 });
  });

  it("does not place while a touch gesture moves as part of scrolling", () => {
    const { stage, onPlaceAtPoint } = renderCanvas();

    fireEvent.pointerDown(stage, { pointerId: 5, button: 0, clientX: 500, clientY: 350 });
    fireEvent.pointerMove(stage, { pointerId: 5, clientX: 500, clientY: 370 });
    fireEvent.pointerUp(stage, { pointerId: 5, button: 0, clientX: 500, clientY: 370 });

    expect(onPlaceAtPoint).not.toHaveBeenCalled();
  });

  it("provides a native keyboard-accessible default placement action", () => {
    const { onPlaceAtPoint } = renderCanvas();
    const suggested = screen.getByRole("button", {
      name: "Розмістити датчик 442 на рекомендованій позиції",
    });

    fireEvent.click(suggested);

    expect(onPlaceAtPoint).toHaveBeenCalledTimes(1);
    expect(onPlaceAtPoint).toHaveBeenCalledWith({ x: 0.25, y: 0.35 });
  });

  it("does not place a second sensor when the operator interacts with an existing marker", () => {
    const { onPlaceAtPoint, onMarkerPointerDown } = renderCanvas();
    const marker = screen.getByRole("button", { name: "Вибрати датчик 441 на схемі" });

    fireEvent.pointerDown(marker, {
      pointerId: 7,
      button: 0,
      clientX: 260,
      clientY: 230,
    });

    expect(onMarkerPointerDown).toHaveBeenCalledTimes(1);
    expect(onPlaceAtPoint).not.toHaveBeenCalled();
  });

  it("keeps ordinary canvas interaction idle when no channel is pending", () => {
    const { stage, onPlaceAtPoint } = renderCanvas({ pendingPlacement: null });

    expect(stage).toHaveAttribute("data-placement-mode", "idle");
    expect(screen.queryByText(/натисніть на фото/)).not.toBeInTheDocument();
    fireEvent.pointerDown(stage, {
      button: 0,
      clientX: 500,
      clientY: 350,
    });
    expect(onPlaceAtPoint).not.toHaveBeenCalled();
  });
});
