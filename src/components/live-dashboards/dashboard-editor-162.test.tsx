import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { createEmptyLiveDashboardDraft, validateLiveDashboardDraft } from "@/features/live-dashboards/model";
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
}: {
  inventory: LiveDashboardInventoryItem[];
  onSave: () => void;
}) {
  const [draft, setDraft] = useState<LiveDashboardDraft>(() => ({
    ...createEmptyLiveDashboardDraft(),
    name: "Raspberry Pi 162-channel acceptance",
  }));

  return (
    <DashboardEditor
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
      onSave={onSave}
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

    expect(screen.getAllByRole("button", { name: "Додати" })).toHaveLength(INVENTORY_SIZE);
    expect(screen.getByText("0 / 64 вибрано", { exact: true })).toBeVisible();

    const search = screen.getByRole("searchbox", { name: "Пошук" });
    fireEvent.change(search, { target: { value: "126-04" } });
    expect(screen.getAllByRole("button", { name: "Додати" })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Додати" }));
    expect(screen.getByText("1 / 64 вибрано", { exact: true })).toBeVisible();
    expect(screen.getByText("126-04 додано.", { exact: true })).toBeVisible();

    fireEvent.change(search, { target: { value: "126-05" } });
    fireEvent.click(screen.getByRole("button", { name: "Додати" }));
    expect(screen.getByText("2 / 64 вибрано", { exact: true })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Перемістити 126-05 вище" }));
    expect(screen.getByRole("button", { name: "Перемістити 126-05 вище" })).toBeDisabled();
    expect(screen.getByLabelText("Конфігурація валідна")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Зберегти" }));
    expect(onSave).toHaveBeenCalledTimes(1);
  });
});
