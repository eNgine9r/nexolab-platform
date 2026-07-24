import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getRefrigerationEquipment, type RefrigerationEquipment } from "@/data/refrigeration";
import {
  createLayoutDraft,
  InMemoryRefrigerationLayoutRepository,
  type RefrigerationLayoutRepository,
} from "@/features/refrigeration/layout-repository";

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

function createRepository(equipment: RefrigerationEquipment) {
  return new InMemoryRefrigerationLayoutRepository({
    drafts: [
      createLayoutDraft({
        id: `draft-${equipment.id}`,
        equipmentId: equipment.id,
        imageId: equipment.image?.id ?? null,
        placements: equipment.sensors.map(({ id, x, y }) => ({ sensorId: id, x, y })),
        createdAt: "2026-07-24T00:00:00.000Z",
      }),
    ],
    now: () => "2026-07-24T00:00:01.000Z",
  });
}

function EditorHarness({ repository }: { repository?: RefrigerationLayoutRepository }) {
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
      repository={repository}
    />
  );
}

function marker(label: string) {
  return screen.getByRole("button", { name: `Вибрати датчик ${label} на схемі` });
}

async function waitForRepositoryReady() {
  await waitFor(() => {
    expect(screen.queryByText("Завантаження чернетки схеми…")).not.toBeInTheDocument();
  });
}

describe("RefrigerationLayoutEditor", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
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
    const file = new File(["photo"], "showcase.webp", { type: "image/webp" });

    fireEvent.change(screen.getByLabelText("Завантажити фото обладнання"), {
      target: { files: [file] },
    });

    expect(createObjectUrl).toHaveBeenCalledWith(file);
    expect(screen.getByText(/showcase\.webp/)).toBeInTheDocument();
    expect(marker("01F")).toHaveAttribute("data-x", originalX);
    expect(screen.getByText("Незбережені зміни")).toBeInTheDocument();
  });

  it("saves the current local draft through the repository and advances its version", async () => {
    const equipment = referenceEquipment();
    const repository = createRepository(equipment);
    render(<EditorHarness repository={repository} />);
    await waitForRepositoryReady();

    fireEvent.click(screen.getByRole("button", { name: "Редагувати схему" }));
    fireEvent.keyDown(marker("01F"), { key: "ArrowRight" });

    const saveButton = screen.getByRole("button", { name: "Зберегти чернетку" });
    expect(saveButton).toBeEnabled();
    fireEvent.click(saveButton);

    expect(await screen.findByText("Чернетку схеми збережено · версія 2")).toBeInTheDocument();
    expect(screen.getByText("Чернетка v2")).toBeInTheDocument();
    expect(screen.getByText("Режим перегляду")).toBeInTheDocument();
    expect(screen.queryByText("Незбережені зміни")).not.toBeInTheDocument();

    const stored = await repository.getDraft(equipment.id);
    expect(stored).toMatchObject({ ok: true, value: { version: 2 } });
  });

  it("preserves local changes when a stale draft save returns a version conflict", async () => {
    const equipment = referenceEquipment();
    const repository = createRepository(equipment);
    render(<EditorHarness repository={repository} />);
    await waitForRepositoryReady();

    const externalSave = await repository.saveDraft({
      equipmentId: equipment.id,
      expectedVersion: 1,
      imageId: equipment.image?.id ?? null,
      placements: equipment.sensors.map(({ id, x, y }, index) => ({
        sensorId: id,
        x: index === 0 ? x + 0.01 : x,
        y,
      })),
    });
    expect(externalSave).toMatchObject({ ok: true, value: { version: 2 } });

    fireEvent.click(screen.getByRole("button", { name: "Редагувати схему" }));
    fireEvent.keyDown(marker("01F"), { key: "ArrowRight", shiftKey: true });
    const localX = marker("01F").getAttribute("data-x");

    fireEvent.click(screen.getByRole("button", { name: "Зберегти чернетку" }));

    expect(await screen.findByText("Конфлікт версій схеми")).toBeInTheDocument();
    expect(screen.getByText(/Локальні позиції та фото не втрачено/)).toBeInTheDocument();
    expect(screen.getByText("Режим редагування")).toBeInTheDocument();
    expect(screen.getByText("Незбережені зміни")).toBeInTheDocument();
    expect(marker("01F")).toHaveAttribute("data-x", localX);
  });
});
