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

function equipment() {
  const value = getRefrigerationEquipment("showcase-106-01");
  if (!value) throw new Error("Reference refrigeration equipment fixture is missing");
  return value;
}

function Harness() {
  const value = equipment();
  const [mode, setMode] = useState<LayoutEditorMode>("view");
  const [selectedId, setSelectedId] = useState(value.sensors[0]?.id ?? null);

  return (
    <RefrigerationLayoutEditor
      equipment={value}
      visibleSensors={value.sensors}
      selectedId={selectedId}
      mode={mode}
      onModeChange={setMode}
      onSelect={setSelectedId}
    />
  );
}

function marker(label = "01F") {
  return screen.getByRole("button", { name: `Вибрати датчик ${label} на схемі` });
}

function recoveryPayload() {
  const value = equipment();
  return createLayoutDraftPayload(
    value.id,
    value.sensors.map(({ id, x, y }, index) => ({
      sensorId: id,
      x: index === 0 ? Math.min(1, x + 0.1) : x,
      y,
    })),
  );
}

async function waitForRepositoryReady() {
  await waitFor(() => {
    expect(screen.queryByText("Завантаження чернетки схеми…")).not.toBeInTheDocument();
  });
}

describe("refrigeration layout recovery", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    window.sessionStorage.clear();
    window.localStorage.clear();
  });

  it("offers explicit restore and keeps recovered geometry dirty until save or cancel", async () => {
    const value = equipment();
    const key = layoutDraftStorageKey(value.id);
    const recovered = recoveryPayload();
    window.sessionStorage.setItem(key, serializeLayoutDraft(recovered));

    render(<Harness />);

    expect(await screen.findByText("Знайдено незбережену чернетку позицій")).toBeInTheDocument();
    expect(marker()).not.toHaveAttribute("data-x", recovered.placements[0]?.x.toFixed(4));

    fireEvent.click(screen.getByRole("button", { name: "Відновити" }));

    expect(screen.getByText("Режим редагування")).toBeInTheDocument();
    expect(screen.getByText("Незбережені зміни")).toBeInTheDocument();
    expect(marker()).toHaveAttribute("data-x", recovered.placements[0]?.x.toFixed(4));
    expect(screen.queryByText("Знайдено незбережену чернетку позицій")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Скасувати" }));

    expect(window.sessionStorage.getItem(key)).toBeNull();
    expect(marker()).toHaveAttribute("data-x", value.sensors[0]?.x.toFixed(4));
    expect(screen.getByText("Режим перегляду")).toBeInTheDocument();
  });

  it("discards a recovery payload without applying it", async () => {
    const value = equipment();
    const key = layoutDraftStorageKey(value.id);
    const originalX = value.sensors[0]?.x.toFixed(4);
    window.sessionStorage.setItem(key, serializeLayoutDraft(recoveryPayload()));

    render(<Harness />);
    expect(await screen.findByText("Знайдено незбережену чернетку позицій")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Відхилити" }));

    expect(window.sessionStorage.getItem(key)).toBeNull();
    expect(marker()).toHaveAttribute("data-x", originalX);
    expect(screen.queryByText("Незбережені зміни")).not.toBeInTheDocument();
  });

  it("autosaves placement edits and supports window-level undo and redo shortcuts", async () => {
    const value = equipment();
    const key = layoutDraftStorageKey(value.id);
    const originalX = markerX(value.sensors[0]?.x);

    render(<Harness />);
    await waitForRepositoryReady();
    fireEvent.click(screen.getByRole("button", { name: "Редагувати схему" }));

    fireEvent.keyDown(marker(), { key: "ArrowRight" });
    const movedX = marker().getAttribute("data-x");
    expect(movedX).not.toBe(originalX);

    await waitFor(() => {
      expect(window.sessionStorage.getItem(key)).not.toBeNull();
    });
    const saved = JSON.parse(window.sessionStorage.getItem(key) ?? "{}") as {
      placements?: Array<{ sensorId: string; x: number; y: number }>;
    };
    expect(saved.placements?.[0]?.x.toFixed(4)).toBe(movedX);
    expect(window.sessionStorage.getItem(key)).not.toContain("blob:");

    fireEvent.keyDown(window, { key: "z", ctrlKey: true });
    expect(marker()).toHaveAttribute("data-x", originalX);
    await waitFor(() => expect(window.sessionStorage.getItem(key)).toBeNull());

    fireEvent.keyDown(window, { key: "z", ctrlKey: true, shiftKey: true });
    expect(marker()).toHaveAttribute("data-x", movedX);
    await waitFor(() => expect(window.sessionStorage.getItem(key)).not.toBeNull());
  });

  it("removes malformed recovery data and keeps the editor available", async () => {
    const value = equipment();
    const key = layoutDraftStorageKey(value.id);
    window.sessionStorage.setItem(key, "{not-json");

    render(<Harness />);
    await waitForRepositoryReady();

    await waitFor(() => expect(window.sessionStorage.getItem(key)).toBeNull());
    expect(screen.queryByText("Знайдено незбережену чернетку позицій")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Редагувати схему" })).toBeEnabled();
  });
});

function markerX(value: number | undefined): string | undefined {
  return value?.toFixed(4);
}
