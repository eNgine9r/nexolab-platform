import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getRefrigerationEquipment } from "@/data/refrigeration";
import {
  createLayoutDraftPayload,
  layoutDraftStorageKey,
  serializeLayoutDraft,
} from "@/features/refrigeration/layout-draft-storage";

import { RefrigerationLayoutEditor, type LayoutEditorMode } from "./refrigeration-layout-editor";

vi.mock("next/image", () => ({
  default: ({ alt, ...props }: React.ImgHTMLAttributes<HTMLImageElement>) => (
    // eslint-disable-next-line @next/next/no-img-element
    <img alt={alt} {...props} />
  ),
}));

function referenceEquipment() {
  const equipment = getRefrigerationEquipment("showcase-106-01");

  if (!equipment) {
    throw new Error("Reference refrigeration equipment fixture is missing");
  }

  return equipment;
}

function EditorHarness() {
  const equipment = referenceEquipment();
  const [mode, setMode] = useState<LayoutEditorMode>("view");
  const [selectedId, setSelectedId] = useState(equipment.sensors[0]?.id ?? null);

  return (
    <RefrigerationLayoutEditor
      equipment={equipment}
      visibleSensors={equipment.sensors}
      selectedId={selectedId}
      mode={mode}
      onModeChange={setMode}
      onSelect={setSelectedId}
    />
  );
}

function marker(label: string) {
  return screen.getByRole("button", {
    name: `Вибрати датчик ${label} на схемі`,
  });
}

describe("RefrigerationLayoutEditor", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    window.sessionStorage.clear();
  });

  it("supports keyboard movement, undo, redo and cancel", () => {
    render(<EditorHarness />);

    fireEvent.click(screen.getByRole("button", { name: "Редагувати схему" }));
    const sensorMarker = marker("01F");
    const originalX = sensorMarker.getAttribute("data-x");

    fireEvent.keyDown(sensorMarker, { key: "ArrowRight" });

    expect(marker("01F")).not.toHaveAttribute("data-x", originalX);
    expect(screen.getByText("Незбережені зміни")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Скасувати останню дію" }));
    expect(marker("01F")).toHaveAttribute("data-x", originalX);

    fireEvent.click(screen.getByRole("button", { name: "Повторити останню дію" }));
    expect(marker("01F")).not.toHaveAttribute("data-x", originalX);

    fireEvent.click(screen.getByRole("button", { name: "Скасувати" }));
    expect(marker("01F")).toHaveAttribute("data-x", originalX);
    expect(screen.getByText("Режим перегляду")).toBeInTheDocument();
  });

  it("supports Ctrl/Cmd undo and redo shortcuts", () => {
    render(<EditorHarness />);

    fireEvent.click(screen.getByRole("button", { name: "Редагувати схему" }));
    const sensorMarker = marker("01F");
    const originalX = sensorMarker.getAttribute("data-x");
    fireEvent.keyDown(sensorMarker, { key: "ArrowRight" });

    fireEvent.keyDown(window, { key: "z", ctrlKey: true });
    expect(marker("01F")).toHaveAttribute("data-x", originalX);

    fireEvent.keyDown(window, {
      key: "z",
      ctrlKey: true,
      shiftKey: true,
    });
    expect(marker("01F")).not.toHaveAttribute("data-x", originalX);
  });

  it("moves a marker with pointer drag using normalized stage coordinates", () => {
    render(<EditorHarness />);

    fireEvent.click(screen.getByRole("button", { name: "Редагувати схему" }));
    const stage = screen.getByTestId("equipment-image-stage");
    stage.getBoundingClientRect = () =>
      ({
        x: 0,
        y: 0,
        top: 0,
        left: 0,
        right: 1000,
        bottom: 600,
        width: 1000,
        height: 600,
        toJSON: () => undefined,
      }) as DOMRect;

    const sensorMarker = marker("01F");
    fireEvent.pointerDown(sensorMarker, {
      pointerId: 1,
      clientX: 138,
      clientY: 126,
    });
    fireEvent.pointerMove(sensorMarker, {
      pointerId: 1,
      clientX: 500,
      clientY: 300,
    });
    fireEvent.pointerUp(sensorMarker, {
      pointerId: 1,
      clientX: 500,
      clientY: 300,
    });

    expect(marker("01F")).toHaveAttribute("data-x", "0.5000");
    expect(marker("01F")).toHaveAttribute("data-y", "0.5000");
  });

  it("previews a validated equipment photo without discarding placements", () => {
    const createObjectUrl = vi.fn(() => "blob:nexolab-equipment-photo");
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: createObjectUrl,
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });

    render(<EditorHarness />);
    fireEvent.click(screen.getByRole("button", { name: "Редагувати схему" }));

    const sensorMarker = marker("01F");
    const originalX = sensorMarker.getAttribute("data-x");
    const file = new File(["photo"], "showcase.webp", {
      type: "image/webp",
    });

    fireEvent.change(screen.getByLabelText("Завантажити фото обладнання"), {
      target: { files: [file] },
    });

    expect(createObjectUrl).toHaveBeenCalledWith(file);
    expect(screen.getByText(/showcase\.webp/)).toBeInTheDocument();
    expect(marker("01F")).toHaveAttribute("data-x", originalX);
    expect(screen.getByText("Незбережені зміни")).toBeInTheDocument();
  });

  it("offers recovery for a valid equipment-scoped draft", async () => {
    const equipment = referenceEquipment();
    const placements = equipment.sensors.map(({ id, x, y }, index) => ({
      sensorId: id,
      x: index === 0 ? 0.75 : x,
      y: index === 0 ? 0.8 : y,
    }));
    window.sessionStorage.setItem(
      layoutDraftStorageKey(equipment.id),
      serializeLayoutDraft(createLayoutDraftPayload(equipment.id, placements, "2026-07-24T19:00:00.000Z")),
    );

    render(<EditorHarness />);

    expect(await screen.findByText("Знайдено відновлювану чернетку")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Відновити" }));

    expect(screen.getByText("Режим редагування")).toBeInTheDocument();
    expect(marker("01F")).toHaveAttribute("data-x", "0.7500");
    expect(marker("01F")).toHaveAttribute("data-y", "0.8000");
  });

  it("removes invalid recovery data safely", async () => {
    const equipment = referenceEquipment();
    const key = layoutDraftStorageKey(equipment.id);
    window.sessionStorage.setItem(key, "not-json");

    render(<EditorHarness />);

    await waitFor(() => expect(window.sessionStorage.getItem(key)).toBeNull());
    expect(screen.queryByText("Знайдено відновлювану чернетку")).not.toBeInTheDocument();
  });
});
