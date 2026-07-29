import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getRefrigerationEquipment } from "@/data/refrigeration";
import {
  createLayoutDraft,
  InMemoryRefrigerationLayoutRepository,
} from "@/features/refrigeration/layout-repository";

import { SensorPlacementManager } from "./sensor-placement-manager";

const addLabel = "Додати вибраний датчик на підкладку";
const replaceLabel = "Замінити датчик у вибраній позиції";
const removeLabel = "Видалити датчик із вибраної позиції";

function fixture() {
  const equipment = getRefrigerationEquipment("showcase-106-01");
  if (!equipment) throw new Error("Reference refrigeration equipment fixture is missing");
  const repository = new InMemoryRefrigerationLayoutRepository({
    drafts: [
      createLayoutDraft({
        id: `draft-${equipment.id}`,
        equipmentId: equipment.id,
        imageId: equipment.image?.id ?? null,
        image: equipment.image,
        placements: equipment.sensors.map(({ id, x, y }) => ({ sensorId: id, x, y })),
        createdAt: "2026-07-29T00:00:00.000Z",
      }),
    ],
    now: () => "2026-07-29T00:00:01.000Z",
  });
  return { equipment, repository };
}

describe("SensorPlacementManager", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("swaps two installed sensors through a versioned repository save", async () => {
    const { equipment, repository } = fixture();
    const first = equipment.sensors[0];
    const second = equipment.sensors[1];
    if (!first || !second) throw new Error("Sensor fixtures are missing");

    render(
      <SensorPlacementManager
        equipment={equipment}
        repository={repository}
        canEdit
        mode="view"
        onModeChange={() => undefined}
        onSelect={() => undefined}
        onAssignmentsChanged={() => undefined}
      />,
    );

    await waitFor(() => expect(screen.getByRole("button", { name: replaceLabel })).toBeEnabled());
    fireEvent.change(screen.getByRole("combobox", { name: "Встановлений датчик" }), {
      target: { value: first.id },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Датчик зі списку" }), {
      target: { value: second.id },
    });
    fireEvent.click(screen.getByRole("button", { name: replaceLabel }));

    await screen.findByText(/поміняно місцями/);
    const result = await repository.getDraft(equipment.id);
    expect(result).toMatchObject({ ok: true, value: { version: 2 } });
    if (!result.ok) throw new Error("Draft save failed");
    expect(result.value.placements).toContainEqual({
      sensorId: second.id,
      x: first.x,
      y: first.y,
    });
    expect(result.value.placements).toContainEqual({
      sensorId: first.id,
      x: second.x,
      y: second.y,
    });
  });

  it("removes a sensor and then allows adding it back from the list", async () => {
    const { equipment, repository } = fixture();
    const removed = equipment.sensors[0];
    if (!removed) throw new Error("Sensor fixture is missing");
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const onModeChange = vi.fn();

    render(
      <SensorPlacementManager
        equipment={equipment}
        repository={repository}
        canEdit
        mode="view"
        onModeChange={onModeChange}
        onSelect={() => undefined}
        onAssignmentsChanged={() => undefined}
      />,
    );

    await waitFor(() => expect(screen.getByRole("button", { name: removeLabel })).toBeEnabled());
    fireEvent.change(screen.getByRole("combobox", { name: "Встановлений датчик" }), {
      target: { value: removed.id },
    });
    fireEvent.click(screen.getByRole("button", { name: removeLabel }));
    await screen.findByText(new RegExp(`${removed.label} видалено`));

    fireEvent.change(screen.getByRole("combobox", { name: "Датчик зі списку" }), {
      target: { value: removed.id },
    });
    expect(screen.getByRole("button", { name: addLabel })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: addLabel }));

    await screen.findByText(new RegExp(`${removed.label} додано`));
    expect(onModeChange).toHaveBeenCalledWith("edit");
    const result = await repository.getDraft(equipment.id);
    expect(result).toMatchObject({ ok: true, value: { version: 3 } });
    if (!result.ok) throw new Error("Draft save failed");
    expect(result.value.placements.some(({ sensorId }) => sensorId === removed.id)).toBe(true);
  });
});
