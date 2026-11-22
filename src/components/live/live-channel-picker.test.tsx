import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import {
  deselectChannels,
  filterPickerGroups,
  groupLiveChannelsByDevice,
  groupSelectionState,
  selectChannels,
} from "@/features/live/channel-picker";
import { liveChannelKey } from "@/features/live/live-telemetry";
import type { TelemetrySample } from "@/lib/telemetry/types";

import { LiveChannelPicker } from "./live-channel-picker";

function sample(equipment: string, channel: string, metric = "temperature.probe", node = "edge-1") {
  return {
    event_id: `${equipment}-${channel}`,
    node_id: node,
    captured_at: "2026-11-22T00:00:00Z",
    metric,
    value: 4,
    unit: "degC",
    quality: "valid",
    source: "test",
    equipment_id: equipment,
    channel_id: channel,
    alarm: null,
    raw_value: 4,
    raw_status: null,
  } as TelemetrySample;
}

const samples = [
  sample("K106", "106-02"),
  sample("K106", "106-01"),
  sample("K106", "106-10"),
  sample("LE01MP-200", "200-power", "electrical.power.active"),
  sample("LE01MP-200", "200-voltage", "electrical.voltage"),
];
const names = { "edge-1/106-01": "Вітрина верх", "edge-1/200-power": "Потужність холодильної лінії" };

describe("channel picker logic (#1671)", () => {
  it("groups by device, uses operator names and sorts naturally", () => {
    const groups = groupLiveChannelsByDevice(samples, names);
    expect(groups.map((group) => group.label)).toEqual(["K106", "LE01MP-200"]);
    expect(groups[0].channels.map((channel) => channel.label)).toEqual(
      ["106-02", "106-10", "Вітрина верх"].sort((a, b) =>
        new Intl.Collator("uk-UA", { numeric: true, sensitivity: "base" }).compare(a, b),
      ),
    );
    const named = groups[0].channels.find((channel) => channel.technicalId === "106-01");
    expect(named?.label).toBe("Вітрина верх");
    expect(named?.key).toBe(liveChannelKey(samples[1]));
  });

  it("searches device, name, technical id, metric and keeps all channels of a matching device", () => {
    const groups = groupLiveChannelsByDevice(samples, names);
    expect(
      filterPickerGroups(groups, "вітрина").flatMap((g) => g.channels.map((c) => c.technicalId)),
    ).toEqual(["106-01"]);
    expect(filterPickerGroups(groups, "voltage")[0].channels).toHaveLength(1);
    expect(filterPickerGroups(groups, "k106")[0].channels).toHaveLength(3);
    expect(filterPickerGroups(groups, "k106 106-10")[0].channels).toHaveLength(1);
    expect(filterPickerGroups(groups, "   ")).toHaveLength(2);
    expect(filterPickerGroups(groups, "немає такого")).toEqual([]);
  });

  it("selects up to the limit without duplicates and reports truncation", () => {
    expect(selectChannels(["a"], ["a", "b", "c"], 3)).toEqual({
      selected: ["a", "b", "c"],
      truncated: false,
    });
    expect(selectChannels(["a", "b"], ["c", "d", "e"], 3)).toEqual({
      selected: ["a", "b", "c"],
      truncated: true,
    });
    expect(deselectChannels(["a", "b", "c"], ["b", "x"])).toEqual(["a", "c"]);
    const group = groupLiveChannelsByDevice(samples)[0];
    expect(groupSelectionState(group, [])).toBe("none");
    expect(groupSelectionState(group, [group.channels[0].key])).toBe("some");
    expect(
      groupSelectionState(
        group,
        group.channels.map((channel) => channel.key),
      ),
    ).toBe("all");
  });
});

function Harness({ limit = 24, initial = [] as string[] }: { limit?: number; initial?: string[] }) {
  const [selected, setSelected] = useState<string[]>(initial);
  return (
    <>
      <LiveChannelPicker
        samples={samples}
        selectedKeys={selected}
        names={names}
        limit={limit}
        onChange={setSelected}
      />
      <output data-testid="selected">{selected.length}</output>
    </>
  );
}

describe("LiveChannelPicker", () => {
  it("shows operator names, selects a whole device and clears everything", () => {
    render(<Harness />);
    expect(screen.getByText("Вітрина верх")).toBeInTheDocument();
    expect(screen.getByTestId("live-channel-picker-count")).toHaveTextContent("Вибрано 0 із 24");
    fireEvent.click(screen.getByLabelText("Вибрати всі канали приладу K106"));
    expect(screen.getByTestId("selected")).toHaveTextContent("3");
    fireEvent.click(screen.getByText("Вибрати всі"));
    expect(screen.getByTestId("selected")).toHaveTextContent("5");
    fireEvent.click(screen.getByText("Зняти всі"));
    expect(screen.getByTestId("selected")).toHaveTextContent("0");
  });

  it("searches, restricts bulk actions to the found channels and keeps groups open while searching", () => {
    render(<Harness />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "voltage" } });
    expect(screen.getByTestId("live-channel-picker-count")).toHaveTextContent("знайдено 1");
    fireEvent.click(screen.getByText("Вибрати знайдені"));
    expect(screen.getByTestId("selected")).toHaveTextContent("1");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "нічого" } });
    expect(screen.getByTestId("live-channel-picker-empty")).toBeInTheDocument();
  });

  it("collapses a device group and announces the limit when a bulk selection is truncated", () => {
    render(<Harness limit={2} />);
    const groups = screen.getAllByTestId("live-channel-picker-group");
    const toggle = within(groups[0]).getByRole("button", { name: /K106/ });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(screen.getByText("Вибрати всі"));
    expect(screen.getByTestId("selected")).toHaveTextContent("2");
    expect(screen.getByTestId("live-channel-picker-message")).toHaveTextContent("ліміт 2");
  });
});
