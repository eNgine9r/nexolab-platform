import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LayoutEditorMode } from "@/components/refrigeration/refrigeration-layout-editor";
import {
  getRefrigerationEquipment,
  type EquipmentImageMetadata,
  type RefrigerationEquipment,
} from "@/data/refrigeration";
import {
  createLayoutDraft,
  InMemoryRefrigerationLayoutRepository,
  type RefrigerationLayoutRepository,
} from "@/features/refrigeration/layout-repository";

import { RefrigerationLayoutWorkspace } from "./refrigeration-layout-workspace";

vi.mock("next/image", () => ({
  default: ({ alt, ...props }: React.ImgHTMLAttributes<HTMLImageElement>) => (
    // eslint-disable-next-line @next/next/no-img-element
    <img alt={alt} {...props} />
  ),
}));

function equipment(): RefrigerationEquipment {
  const value = getRefrigerationEquipment("showcase-106-01");
  if (!value) throw new Error("Reference refrigeration equipment is missing");
  return value;
}

function image(): EquipmentImageMetadata {
  return {
    id: "image-1",
    fileName: "showcase.webp",
    mimeType: "image/webp",
    widthPx: 1200,
    heightPx: 800,
    sizeBytes: 1024,
    sourceUrl: "http://storage.local/showcase.webp?signature=1",
    alt: "Фото вітрини",
    updatedAt: "2026-07-25T10:00:00Z",
  };
}

function repository(options: { withImage?: boolean } = {}) {
  const fixture = equipment();
  const seededImage = options.withImage ? image() : null;
  let timestamp = 0;
  let revision = 0;
  let imageId = 1;
  return new InMemoryRefrigerationLayoutRepository({
    drafts: [
      createLayoutDraft({
        id: `draft-${fixture.id}`,
        equipmentId: fixture.id,
        image: seededImage,
        placements: fixture.sensors.map(({ id, x, y }) => ({
          sensorId: id,
          x,
          y,
        })),
        createdAt: "2026-07-25T09:00:00Z",
      }),
    ],
    now: () => `2026-07-25T10:00:${String(++timestamp).padStart(2, "0")}Z`,
    createId: () => `revision-${++revision}`,
    createImageId: () => `uploaded-image-${++imageId}`,
  });
}

function Harness({ repository: store }: { repository: RefrigerationLayoutRepository }) {
  const fixture = equipment();
  const [mode, setMode] = useState<LayoutEditorMode>("view");
  const [selectedId, setSelectedId] = useState(fixture.sensors[0]?.id ?? null);

  return (
    <RefrigerationLayoutWorkspace
      equipment={fixture}
      visibleSensors={fixture.sensors}
      selectedId={selectedId}
      mode={mode}
      onModeChange={setMode}
      onSelect={setSelectedId}
      repository={store}
      runtimeMode="live"
      actorId="operator-1"
    />
  );
}

function marker(label: string) {
  return screen.getByRole("button", {
    name: `Вибрати датчик ${label} на схемі`,
  });
}

async function waitForWorkspace() {
  await waitFor(() => {
    expect(
      screen.queryByText("Завантаження production-схеми, публікації та історії…"),
    ).not.toBeInTheDocument();
  });
  await waitFor(() => {
    expect(screen.queryByText("Завантаження чернетки схеми…")).not.toBeInTheDocument();
  });
}

describe("RefrigerationLayoutWorkspace", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:nexolab-upload-preview"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  it("uploads a real photo and persists its image ID into a new draft version", async () => {
    const store = repository();
    render(<Harness repository={store} />);
    await waitForWorkspace();

    const file = new File(["image-bytes"], "production.webp", {
      type: "image/webp",
    });
    fireEvent.change(screen.getByLabelText("Вибрати production-фото обладнання"), {
      target: { files: [file] },
    });

    expect(await screen.findByText(/завантажено та прив’язано до чернетки v2/i)).toBeInTheDocument();
    expect(URL.createObjectURL).toHaveBeenCalledWith(file);

    const stored = await store.getDraft(equipment().id);
    expect(stored).toMatchObject({
      ok: true,
      value: {
        version: 2,
        imageId: expect.stringMatching(/^uploaded-image-/),
      },
    });
  });

  it("publishes immutable revisions, refreshes history and restores into a new draft", async () => {
    const store = repository({ withImage: true });
    render(<Harness repository={store} />);
    await waitForWorkspace();

    fireEvent.click(screen.getByRole("button", { name: "Опублікувати поточну чернетку" }));

    expect(await screen.findByText("Опубліковано ревізію r1.")).toBeInTheDocument();
    expect(screen.getAllByText("r1").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/operator-1/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Відновити" }));

    expect(await screen.findByText(/Ревізію r1 відновлено як чернетку v3/)).toBeInTheDocument();
    expect(screen.getByText("Режим редагування")).toBeInTheDocument();

    const stored = await store.getDraft(equipment().id);
    expect(stored).toMatchObject({ ok: true, value: { version: 3 } });
    const history = await store.listHistory(equipment().id);
    expect(history).toMatchObject({ ok: true, value: [{ revision: 1 }] });
  });

  it("preserves local marker edits on conflict and reloads only after explicit confirmation", async () => {
    const store = repository({ withImage: true });
    render(<Harness repository={store} />);
    await waitForWorkspace();

    const fixture = equipment();
    const externalSave = await store.saveDraft({
      equipmentId: fixture.id,
      expectedVersion: 1,
      imageId: image().id,
      placements: fixture.sensors.map(({ id, x, y }, index) => ({
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

    expect(await screen.findByText("End-to-end конфлікт версій")).toBeInTheDocument();
    expect(screen.getByText(/Локальні позиції та preview фото не перезаписано/)).toBeInTheDocument();
    expect(marker("01F")).toHaveAttribute("data-x", localX);
    expect(screen.getByText("Незбережені зміни")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Завантажити серверну v2" }));

    expect(window.confirm).toHaveBeenCalled();
    expect(await screen.findByText("Завантажено серверну чернетку v2.")).toBeInTheDocument();
    expect(screen.getByText("Режим перегляду")).toBeInTheDocument();
    expect(screen.queryByText("Незбережені зміни")).not.toBeInTheDocument();
    expect(marker("01F")).not.toHaveAttribute("data-x", localX);
  });
});
