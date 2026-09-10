import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { refrigerationEquipment } from "@/data/refrigeration";
import type {
  AvailableSensor,
  EquipmentLifecycleRepository,
  SensorBinding,
} from "@/features/refrigeration/equipment-lifecycle-repository";
import {
  createLayoutDraft,
  InMemoryRefrigerationLayoutRepository,
} from "@/features/refrigeration/layout-repository";
import type { StagedSensorConfiguration } from "@/features/refrigeration/sensor-configuration";

import { CameraScopedLayoutEditor } from "./camera-scoped-layout-editor-implementation";
vi.mock("@/components/refrigeration/camera-scoped-image-canvas", () => ({
  CameraScopedImageCanvas: () => <div data-testid="mock-camera-canvas" />,
}));

vi.mock("@/components/refrigeration/sensor-placement-manager", () => ({
  SensorPlacementManager: ({
    configuration,
    onConfigurationChange,
  }: {
    configuration: readonly StagedSensorConfiguration[];
    onConfigurationChange: (next: StagedSensorConfiguration[]) => void;
  }) => {
    const sensor = configuration[0];
    return (
      <div
        data-testid="mock-placement-manager"
        data-label={sensor?.label ?? ""}
        data-x={sensor?.x ?? ""}
        data-temperature={sensor?.temperatureC ?? ""}
      >
        <button
          type="button"
          onClick={() =>
            onConfigurationChange(
              configuration.map((item) =>
                item.id === sensor?.id ? { ...item, label: "Staged label", x: 0.77 } : item,
              ),
            )
          }
        >
          stage edit
        </button>
      </div>
    );
  },
}));
const equipmentFixture = refrigerationEquipment[0];
if (!equipmentFixture) throw new Error("Refrigeration equipment fixture is required");
const equipment = {
  ...equipmentFixture,
  id: "showcase-kk2",
  name: "Showcase KK2",
  totalSensors: 48,
};

const binding: SensorBinding = {
  id: "binding-106-03",
  equipmentId: equipment.id,
  nodeId: "edge-01",
  channelId: "106-03",
  slotKey: "front-01",
  label: "Persisted label",
  side: "front",
  shelf: 1,
  position: 1,
  version: 1,
  boundBy: "operator",
  boundAt: "2026-09-10T16:00:00.000Z",
  unboundBy: null,
  unboundAt: null,
};
const initialChannel: AvailableSensor = {
  channelId: "106-03",
  inventoryNumber: null,
  metric: "temperature",
  unit: "degC",
  latestValue: 4.2,
  quality: "valid",
  capturedAt: "2026-09-10T16:00:00.000Z",
  isBound: true,
  boundEquipmentId: equipment.id,
  boundSlotKey: "front-01",
};
const enrichedChannel: AvailableSensor = {
  ...initialChannel,
  inventoryNumber: "441",
  latestValue: 7.5,
  capturedAt: "2026-09-10T16:45:00.000Z",
};
const bindings = [binding];

function editorProps(
  channels: readonly AvailableSensor[],
  currentBindings: readonly SensorBinding[] = bindings,
) {
  return {
    equipment,
    organizationId: "org-equipment-map",
    visibleSensors: [],
    selectedId: null,
    mode: "edit" as const,
    channels,
    bindings: currentBindings,
  };
}
describe("CameraScopedLayoutEditor metadata refresh", () => {
  it("preserves staged layout edits when channel metadata changes", async () => {
    const draft = createLayoutDraft({
      id: "draft-showcase-kk2",
      equipmentId: equipment.id,
      placements: [{ sensorId: "106-03", x: 0.2, y: 0.3 }],
      createdAt: "2026-09-10T16:00:00.000Z",
    });
    const repository = new InMemoryRefrigerationLayoutRepository({ drafts: [draft] });
    const getDraft = vi.spyOn(repository, "getDraft");
    const lifecycleRepository = {} as EquipmentLifecycleRepository;
    const callbacks = {
      onModeChange: vi.fn(),
      onSelect: vi.fn(),
      onEquipmentChange: vi.fn(),
      onDraftChange: vi.fn(),
    };

    const { rerender } = render(
      <CameraScopedLayoutEditor
        {...editorProps([initialChannel])}
        {...callbacks}
        repository={repository}
        lifecycleRepository={lifecycleRepository}
      />,
    );
    const manager = await screen.findByTestId("mock-placement-manager");
    expect(manager).toHaveAttribute("data-label", "Persisted label");
    expect(manager).toHaveAttribute("data-x", "0.2");
    expect(manager).toHaveAttribute("data-temperature", "4.2");
    expect(getDraft).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "stage edit" }));
    expect(manager).toHaveAttribute("data-label", "Staged label");
    expect(manager).toHaveAttribute("data-x", "0.77");

    rerender(
      <CameraScopedLayoutEditor
        {...editorProps([enrichedChannel], [{ ...binding }])}
        {...callbacks}
        repository={repository}
        lifecycleRepository={lifecycleRepository}
      />,
    );

    await waitFor(() => expect(manager).toHaveAttribute("data-temperature", "7.5"));
    expect(manager).toHaveAttribute("data-label", "Staged label");
    expect(manager).toHaveAttribute("data-x", "0.77");
    expect(getDraft).toHaveBeenCalledTimes(1);
  });
});
