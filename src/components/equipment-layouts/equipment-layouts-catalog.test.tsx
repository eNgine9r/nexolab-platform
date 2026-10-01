import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { getRefrigerationEquipment } from "@/data/refrigeration";
import type { LayoutCatalogReadyItem } from "@/features/equipment-layouts/layout-catalog";

import { EquipmentLayoutsCatalog } from "./equipment-layouts-catalog";

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: { children: ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/equipment-layouts",
  useSearchParams: () => new URLSearchParams("q=SHOW&zone=A"),
  useRouter: () => ({ replace: vi.fn() }),
}));

function item(): LayoutCatalogReadyItem {
  const reference = getRefrigerationEquipment("showcase-106-01");
  if (!reference) throw new Error("Missing equipment fixture");
  return {
    kind: "ready",
    equipment: {
      ...reference,
      code: "SHOW-106",
      zone: "A",
      lifecycleStatus: "active",
      nodeId: null,
      climateChamberId: null,
    },
    draft: {
      id: "draft-1",
      equipmentId: reference.id,
      version: 1,
      etag: 'W/"1"',
      imageId: "image-1",
      image: {
        id: "image-1",
        fileName: "layout.png",
        mimeType: "image/png",
        widthPx: 1200,
        heightPx: 800,
        sizeBytes: 100,
        sourceUrl: "/layout.png",
        alt: "Схема",
        updatedAt: "2026-10-01T00:00:00Z",
      },
      placements: [],
      createdAt: "2026-10-01T00:00:00Z",
      updatedAt: "2026-10-01T00:00:00Z",
    },
    published: null,
    layoutState: "draft-only",
  };
}

describe("direct scheme navigation from the catalog", () => {
  it("opens the selected scheme read-only by default and preserves catalog filters", () => {
    render(<EquipmentLayoutsCatalog state="ready" items={[item()]} error={null} onRetry={() => undefined} />);
    const href = screen.getByRole("link", { name: "Відкрити схему SHOW-106" }).getAttribute("href")!;
    const target = new URL(href, "http://nexolab.invalid");
    expect(target.pathname).toBe("/refrigeration/showcase-106-01");
    expect(target.searchParams.get("tab")).toBe("scheme");
    expect(target.searchParams.get("mode")).toBeNull();
    expect(target.searchParams.get("returnTo")).toBe("/equipment-layouts?q=SHOW&zone=A");
    expect(screen.queryByRole("link", { name: /Редагувати схему/ })).not.toBeInTheDocument();
  });

  it("offers direct editing only for an editable object with a verified draft image", () => {
    const current = item();
    const { rerender } = render(
      <EquipmentLayoutsCatalog
        state="ready"
        items={[current]}
        error={null}
        onRetry={() => undefined}
        canEditDraft
      />,
    );
    const edit = screen.getByRole("link", { name: "Редагувати схему SHOW-106" });
    expect(new URL(edit.getAttribute("href")!, "http://nexolab.invalid").searchParams.get("mode")).toBe(
      "edit",
    );
    for (const guarded of [
      { ...current, equipment: { ...current.equipment, lifecycleStatus: "retired" as const } },
      { ...current, draft: { ...current.draft, image: null, imageId: null } },
    ]) {
      rerender(
        <EquipmentLayoutsCatalog
          state="ready"
          items={[guarded]}
          error={null}
          onRetry={() => undefined}
          canEditDraft
        />,
      );
      expect(screen.queryByRole("link", { name: /Редагувати схему/ })).not.toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Відкрити схему SHOW-106" })).toBeVisible();
    }
  });
  it("requires the sensor-configuration save permission only on camera-scoped cards", () => {
    const camera = item();
    camera.equipment.nodeId = "camera-node";
    const { rerender } = render(
      <EquipmentLayoutsCatalog
        state="ready"
        items={[camera]}
        error={null}
        onRetry={() => undefined}
        canEditDraft
      />,
    );
    expect(screen.queryByRole("link", { name: /Редагувати схему/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Відкрити схему SHOW-106" })).toBeVisible();
    rerender(
      <EquipmentLayoutsCatalog
        state="ready"
        items={[camera]}
        error={null}
        onRetry={() => undefined}
        canEditDraft
        canManageEquipment
      />,
    );
    expect(screen.getByRole("link", { name: "Редагувати схему SHOW-106" })).toBeVisible();
  });
});
