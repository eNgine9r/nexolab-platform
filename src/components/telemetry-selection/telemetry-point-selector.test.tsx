import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  buildTelemetryPointHierarchy,
  collectTelemetryPointBranchIds,
  telemetryPointSelectionKey,
  type TelemetryPointDescriptor,
} from "@/features/telemetry-selection/hierarchy";

import { TelemetryPointSelector } from "./telemetry-point-selector";

const ORGANIZATION_ID = "org-selector";

function point(
  overrides: Partial<TelemetryPointDescriptor> &
    Pick<TelemetryPointDescriptor, "channelId" | "metric" | "unit">,
): TelemetryPointDescriptor {
  return {
    organizationId: ORGANIZATION_ID,
    laboratory: { id: "lab-1", label: "Laboratory 1" },
    zone: { id: "zone-a", label: "Zone A" },
    equipmentType: { id: "energy-meter", label: "Energy meters" },
    equipment: { id: "LE-01MP", label: "LE-01MP Meter 01" },
    nodeId: "edge-01",
    channelLabel: overrides.channelId,
    metricLabel: overrides.metric,
    ...overrides,
  };
}

function points(): TelemetryPointDescriptor[] {
  return [
    point({ channelId: "voltage", channelLabel: "Voltage", metric: "voltage", unit: "V" }),
    point({ channelId: "current", channelLabel: "Current", metric: "current", unit: "A" }),
    point({ channelId: "power", channelLabel: "Active power", metric: "active_power", unit: "W" }),
    point({
      zone: { id: "zone-b", label: "Zone B" },
      equipmentType: { id: "temperature-controller", label: "Temperature controllers" },
      equipment: { id: "XR170C-106", label: "XR170C Unit 106" },
      channelId: "106-03",
      channelLabel: "Probe 03",
      metric: "temperature.probe",
      metricLabel: "Temperature",
      unit: "degC",
    }),
  ];
}

function setup(options: { value?: string[]; maxSelection?: number; expanded?: boolean } = {}) {
  const descriptors = points();
  const hierarchy = buildTelemetryPointHierarchy(descriptors, ORGANIZATION_ID);
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(
    <TelemetryPointSelector
      hierarchy={hierarchy}
      value={options.value ?? []}
      maxSelection={options.maxSelection}
      initialExpandedNodeIds={options.expanded ? collectTelemetryPointBranchIds(hierarchy) : []}
      onConfirm={onConfirm}
      onCancel={onCancel}
    />,
  );
  return { hierarchy, descriptors, onConfirm, onCancel };
}

describe("TelemetryPointSelector", () => {
  it("exposes hierarchical ARIA state and restores committed selection on Cancel", () => {
    const descriptors = points();
    const voltageKey = telemetryPointSelectionKey(descriptors[0]);
    const { onCancel } = setup({ value: [voltageKey], expanded: true });

    const tree = screen.getByRole("tree", { name: "Точки телеметрії" });
    expect(tree).toHaveAttribute("aria-multiselectable", "true");

    const meter = screen.getByRole("treeitem", { name: /LE-01MP Meter 01/ });
    expect(meter).toHaveAttribute("aria-level", "4");
    expect(meter).toHaveAttribute("aria-checked", "mixed");

    const search = screen.getByRole("searchbox", { name: "Пошук" });
    fireEvent.change(search, { target: { value: "Current" } });
    expect(screen.getByRole("treeitem", { name: /Current/ })).toBeVisible();
    expect(screen.queryByRole("treeitem", { name: /Voltage/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("treeitem", { name: /Current/ }));
    expect(screen.getByTestId("telemetry-selection-count")).toHaveTextContent("2");

    fireEvent.click(screen.getByRole("button", { name: "Скасувати" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(search).toHaveValue("");
    expect(screen.getByTestId("telemetry-selection-count")).toHaveTextContent("1");
    expect(screen.getByRole("treeitem", { name: /LE-01MP Meter 01/ })).toHaveAttribute(
      "aria-checked",
      "mixed",
    );
  });

  it("supports keyboard tree traversal, expansion and selection without pointer input", () => {
    setup();

    const tree = screen.getByRole("tree", { name: "Точки телеметрії" });
    const laboratory = within(tree).getByRole("treeitem", { name: /Laboratory 1/ });
    laboratory.focus();
    expect(laboratory).toHaveFocus();
    expect(laboratory).toHaveAttribute("aria-expanded", "false");

    fireEvent.keyDown(laboratory, { key: "ArrowRight" });
    expect(laboratory).toHaveAttribute("aria-expanded", "true");

    fireEvent.keyDown(laboratory, { key: "ArrowDown" });
    const zoneA = within(tree).getByRole("treeitem", { name: /Zone A/ });
    expect(zoneA).toHaveFocus();

    fireEvent.keyDown(zoneA, { key: " " });
    expect(zoneA).toHaveAttribute("aria-checked", "true");
    expect(screen.getByTestId("telemetry-selection-count")).toHaveTextContent("3");

    fireEvent.keyDown(zoneA, { key: "ArrowLeft" });
    expect(laboratory).toHaveFocus();

    const search = screen.getByRole("searchbox", { name: "Пошук" });
    search.focus();
    fireEvent.keyDown(search, { key: "ArrowDown" });
    expect(laboratory).toHaveFocus();
  });

  it("enforces an atomic selection limit and confirms keys in canonical hierarchy order", () => {
    const { hierarchy, descriptors, onConfirm } = setup({ maxSelection: 2, expanded: true });
    const meter = screen.getByRole("treeitem", { name: /LE-01MP Meter 01/ });

    fireEvent.click(meter);
    expect(screen.getByRole("status")).toHaveTextContent("Ліміт вибору — 2");
    expect(screen.getByTestId("telemetry-selection-count")).toHaveTextContent("0 / 2");

    const power = screen.getByRole("treeitem", { name: /Active power/ });
    const voltage = screen.getByRole("treeitem", { name: /Voltage/ });
    fireEvent.click(power);
    fireEvent.click(voltage);
    fireEvent.click(screen.getByRole("button", { name: "Підтвердити вибір" }));

    const expected = hierarchy.orderedLeafKeys.filter((key) =>
      [telemetryPointSelectionKey(descriptors[0]), telemetryPointSelectionKey(descriptors[2])].includes(key),
    );
    expect(onConfirm).toHaveBeenCalledWith(expected);
  });

  it("keeps a large expanded catalog bounded and asks the operator to narrow search", () => {
    const largePoints = Array.from({ length: 500 }, (_, index) =>
      point({
        zone: { id: `zone-${index % 8}`, label: `Zone ${index % 8}` },
        equipment: { id: `meter-${index}`, label: `Meter ${index}` },
        channelId: `channel-${index}`,
        channelLabel: `Channel ${index}`,
        metric: "active_power",
        unit: "W",
      }),
    );
    const hierarchy = buildTelemetryPointHierarchy(largePoints, ORGANIZATION_ID);
    render(
      <TelemetryPointSelector
        hierarchy={hierarchy}
        value={[]}
        maxVisibleNodes={80}
        initialExpandedNodeIds={collectTelemetryPointBranchIds(hierarchy)}
        onConfirm={vi.fn()}
      />,
    );

    expect(screen.getAllByRole("treeitem")).toHaveLength(80);
    expect(screen.getByRole("status")).toHaveTextContent("Показано перші 80 вузлів");
  });
});
