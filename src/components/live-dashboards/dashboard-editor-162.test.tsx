import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  addDashboardDraftItem,
  createEmptyLiveDashboardDraft,
  draftToWrite,
  validateLiveDashboardDraft,
} from "@/features/live-dashboards/model";
import type { LiveDashboardDraft, LiveDashboardInventoryItem } from "@/features/live-dashboards/types";

import { DashboardEditor } from "./dashboard-editor";

const INVENTORY_SIZE = 162;
const QUALITIES = ["valid", "sensor_error", "communication_error", "unknown"] as const;

function createInventoryItem(index: number): LiveDashboardInventoryItem {
  const unit = 101 + Math.floor(index / 6);
  const channel = (index % 6) + 1;
  const channelId = `${unit}-${String(channel).padStart(2, "0")}`;
  const quality = QUALITIES[index % QUALITIES.length];
  const alarm = index % 11 === 0 ? "high" : index % 13 === 0 ? "low" : null;

  return {
    key: `${encodeURIComponent(channelId)}|temperature.probe`,
    channel_ref_id: `channel-ref-${index + 1}`,
    node_id: "edge-01",
    equipment_id: `K${unit}`,
    equipment_name: `Dixell XJP60D K${unit}`,
    climate_chamber_id: "chamber-1",
    climate_chamber_code: "KK1",
    climate_chamber_name: "Кліматична камера 1",
    equipment_type: "temperature_controller",
    laboratory: "Лабораторія А",
    zone: "Зона 1",
    channel_id: channelId,
    channel_name: `Sensor ${index + 1}`,
    metric: "temperature.probe",
    native_unit: "degC",
    source: "dixell-xjp60d",
    quality,
    alarm,
    latest: null,
  };
}

function EditorHarness({
  inventory,
  onSave,
  initialDraft,
}: {
  inventory: LiveDashboardInventoryItem[];
  onSave: (draft: LiveDashboardDraft) => void;
  initialDraft?: LiveDashboardDraft;
}) {
  const [draft, setDraft] = useState<LiveDashboardDraft>(() => ({
    ...createEmptyLiveDashboardDraft(),
    name: "Raspberry Pi 162-channel acceptance",
    ...initialDraft,
  }));

  return (
    <DashboardEditor
      organizationId="organization-1"
      draft={draft}
      setDraft={setDraft}
      inventory={{
        items: inventory,
        status: "ready",
        error: null,
        retry: vi.fn(),
      }}
      validation={validateLiveDashboardDraft(draft)}
      conflict={null}
      saving={false}
      saveError={null}
      onSave={() => onSave(draft)}
      onCancel={vi.fn()}
      onUseServerVersion={vi.fn()}
      onSaveAsCopy={vi.fn()}
    />
  );
}

describe("DashboardEditor Raspberry Pi-sized inventory", () => {
  it("renders, searches, selects, reorders and validates against 162 channels", () => {
    const inventory = Array.from({ length: INVENTORY_SIZE }, (_, index) => createInventoryItem(index));
    const onSave = vi.fn();
    render(<EditorHarness inventory={inventory} onSave={onSave} />);

    expect(screen.getByText("0 / 64 вибрано", { exact: true })).toBeVisible();

    const search = screen.getByRole("searchbox", { name: "Пошук" });
    fireEvent.change(search, { target: { value: "126-04" } });
    fireEvent.click(screen.getByRole("treeitem", { name: /Sensor 154/ }));
    fireEvent.click(screen.getByRole("button", { name: "Підтвердити вибір" }));
    expect(screen.getByText("1 / 64 вибрано", { exact: true })).toBeVisible();

    fireEvent.change(search, { target: { value: "126-05" } });
    fireEvent.click(screen.getByRole("treeitem", { name: /Sensor 155/ }));
    fireEvent.click(screen.getByRole("button", { name: "Підтвердити вибір" }));
    expect(screen.getByText("2 / 64 вибрано", { exact: true })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Перемістити 126-05 вище" }));
    expect(screen.getByRole("button", { name: "Перемістити 126-05 вище" })).toBeDisabled();
    expect(screen.getByLabelText("Конфігурація валідна")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Зберегти" }));
    expect(onSave).toHaveBeenCalledTimes(1);
  });
});

describe("DashboardEditor supported visualizations", () => {
  it("offers supported types for a new item without offering an incomplete Gauge", () => {
    const inventory = [createInventoryItem(0)];
    const draft = addDashboardDraftItem(
      { ...createEmptyLiveDashboardDraft(), name: "New monitoring" },
      inventory[0],
    ).draft;
    render(<EditorHarness inventory={inventory} initialDraft={draft} onSave={vi.fn()} />);
    const visualization = screen.getByLabelText("Візуалізація");
    expect(screen.queryByRole("option", { name: "Індикатор", exact: true })).not.toBeInTheDocument();
    for (const value of ["line", "area", "value"]) {
      fireEvent.change(visualization, { target: { value } });
      expect(visualization).toHaveValue(value);
      expect(screen.getByLabelText("Конфігурація валідна")).toBeVisible();
    }
  });

  it("preserves a legacy Gauge through unrelated edits and converts only on explicit choice", () => {
    const inventory = [createInventoryItem(0)];
    const draft = addDashboardDraftItem(
      { ...createEmptyLiveDashboardDraft(), id: "legacy-dashboard", name: "Legacy indicator" },
      inventory[0],
    ).draft;
    draft.items[0].visualization = "gauge";
    const onSave = vi.fn();
    render(<EditorHarness inventory={inventory} initialDraft={draft} onSave={onSave} />);
    const visualization = screen.getByLabelText("Візуалізація");
    expect(visualization).toHaveValue("gauge");
    expect(screen.getByRole("option", { name: "Значення (старий індикатор)" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Назва"), { target: { value: "Renamed legacy" } });
    fireEvent.click(screen.getByRole("button", { name: "Зберегти", exact: true }));
    const retained = onSave.mock.calls.at(-1)![0] as LiveDashboardDraft;
    expect(draftToWrite(retained).items[0].visualization).toBe("gauge");
    expect(retained.items[0]).toEqual(draft.items[0]);
    fireEvent.change(visualization, { target: { value: "value" } });
    expect(screen.queryByRole("option", { name: "Значення (старий індикатор)" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Зберегти", exact: true }));
    const converted = onSave.mock.calls.at(-1)![0] as LiveDashboardDraft;
    expect(converted.items[0]).toEqual({ ...draft.items[0], visualization: "value" });
    expect(draftToWrite(converted).items[0].visualization).toBe("value");
  });
});
