import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StateLaneRow } from "@/components/charts/state-lane-row";
import { DashboardStateLanes } from "@/components/live-dashboards/dashboard-state-lanes";
import { buildSavedDashboardChartGroups } from "@/features/live-dashboards/chart";
import { dashboardItemIdentity } from "@/features/live-dashboards/model";
import { buildDashboardStateLanes } from "@/features/live-dashboards/state-lanes";
import type { LiveDashboardItem, LiveDashboardSeries } from "@/features/live-dashboards/types";

import { DIGITAL_METRICS, digitalLanesForMetric, isDigitalMetric } from "./digital-channels";
import { appendIntervalSample, createIntervalSampleColumns } from "./interval-statistics";
import { buildStateLane, laneStateAt, summarizeLane } from "./state-lanes";

const T0 = Date.parse("2026-11-10T00:00:00Z");

function columns(points: readonly [number, number | null][]) {
  const result = createIntervalSampleColumns();
  for (const [seconds, value] of points) appendIntervalSample(result, T0 + seconds * 1_000, value);
  return result;
}

describe("digital channel taxonomy (#1679)", () => {
  it("classifies only metrics the drivers really deliver and invents no door/fan state", () => {
    expect([...DIGITAL_METRICS].sort()).toEqual(
      [
        "compressor.state",
        "controller.alarm_state",
        "controller.alarm_state_bits",
        "controller.relay_state_bits",
        "fan.evaporator.state",
        "refrigeration.control_state",
      ].sort(),
    );
    expect(isDigitalMetric("temperature.probe")).toBe(false);
    expect(isDigitalMetric("door.state")).toBe(false);
    expect(digitalLanesForMetric("compressor.speed")).toEqual([]);
  });

  it("decodes binary states, the defrost code and relay bits; unsupported values are not guessed", () => {
    const compressor = digitalLanesForMetric("compressor.state")[0];
    expect([compressor.decode(1), compressor.decode(0), compressor.decode(2), compressor.decode(-1)]).toEqual(
      ["on", "off", null, null],
    );
    const defrost = digitalLanesForMetric("refrigeration.control_state")[0];
    expect([defrost.decode(3), defrost.decode(1), defrost.decode(0), defrost.decode(9)]).toEqual([
      "on",
      "off",
      "off",
      null,
    ]);
    const relays = digitalLanesForMetric("controller.relay_state_bits");
    expect(relays).toHaveLength(4);
    expect(relays.map((lane) => lane.decode(0b0101))).toEqual(["on", "off", "on", "off"]);
    expect(relays[0].decode(1.5)).toBeNull();
    const bits = digitalLanesForMetric("controller.alarm_state_bits")[0];
    expect([bits.decode(0), bits.decode(8)]).toEqual(["off", "on"]);
  });
});

describe("state lane builder", () => {
  const decode = (value: number) => (value === 1 ? ("on" as const) : value === 0 ? ("off" as const) : null);

  it("holds ON/OFF between valid polls and merges equal neighbours", () => {
    const lane = buildStateLane(
      columns([
        [0, 0],
        [10, 0],
        [20, 1],
        [30, 1],
        [40, 0],
      ]),
      T0,
      T0 + 60_000,
      decode,
    );
    expect(lane.map((entry) => [entry.state, (entry.toMs - entry.fromMs) / 1000])).toEqual([
      ["off", 20],
      ["on", 20],
    ]);
  });

  it("marks a failed poll UNKNOWN (never OFF) and leaves a silent gap as NO DATA", () => {
    const lane = buildStateLane(
      columns([
        [0, 1],
        [10, 1],
        [20, null],
        [30, 1],
        [40, 1],
        [1000, 1],
      ]),
      T0,
      T0 + 2_000_000,
      decode,
    );
    const states = lane.map((entry) => entry.state);
    expect(states).toContain("unknown");
    expect(states).not.toContain("off");
    // The 40 s → 1000 s silence produced no interval at all (NO DATA).
    expect(laneStateAt(lane, T0 + 500_000)).toBeNull();
    expect(laneStateAt(lane, T0 + 5_000)).toBe("on");
    expect(laneStateAt(lane, T0 + 15_000)).toBe("unknown");
  });

  it("treats a value the lane cannot represent as UNKNOWN, clips to the window and summarises exactly", () => {
    const lane = buildStateLane(
      columns([
        [0, 1],
        [10, 1],
        [20, 2],
        [30, 2],
        [40, 0],
        [50, 0],
      ]),
      T0 + 5_000,
      T0 + 45_000,
      decode,
    );
    expect(lane[0]).toMatchObject({ state: "on", fromMs: T0 + 5_000 });
    expect(lane.at(-1)).toMatchObject({ state: "off", toMs: T0 + 45_000 });
    const summary = summarizeLane(lane);
    expect(summary.onMs).toBe(15_000); // 0→10 s clipped to 5 s, plus 10→20 s held ON
    expect(summary.offMs).toBe(5_000);
    expect(summary.unknownMs).toBe(20_000);
    expect(summary.coveredMs).toBe(summary.onMs + summary.offMs);
    expect(summary.transitions).toBe(0); // UNKNOWN resets the previous known state
    expect(buildStateLane(columns([[0, 1]]), T0, T0 + 1000, decode)).toEqual([]);
  });
});

function item(
  id: string,
  metric: string,
  visualization: LiveDashboardItem["visualization"] = "line",
): LiveDashboardItem {
  return {
    id,
    position: Number(id.replace(/\D/g, "")) || 1,
    channel_ref_id: `ref-${id}`,
    channel_id: id,
    metric,
    native_unit: metric.endsWith("bits") ? "bitfield" : "state",
    visualization,
    color: "#22AAFF",
    display_unit: null,
  };
}

describe("Saved Dashboard state lanes", () => {
  const relay = item("relay-1", "controller.relay_state_bits");
  const compressor = item("comp-2", "compressor.state");
  const temp = item("temp-3", "temperature.probe");
  const series: LiveDashboardSeries[] = [relay, compressor, temp].map((entry) => ({
    item: entry,
    latest: null,
    history: [],
  }));
  const store = new Map([
    [
      dashboardItemIdentity(relay),
      columns([
        [0, 0b01],
        [10, 0b01],
        [20, 0b10],
        [30, 0b10],
      ]),
    ],
    [
      dashboardItemIdentity(compressor),
      columns([
        [0, 1],
        [10, 1],
        [20, null],
        [30, 1],
      ]),
    ],
  ]);
  const domain = { fromMs: T0, toMs: T0 + 40_000 };

  it("builds one lane per decoded state, only for known digital items, from raw columns", () => {
    const lanes = buildDashboardStateLanes(series, (identity) => store.get(identity), domain);
    expect(lanes.map((lane) => lane.label.split(" · ")[0])).toEqual([
      "Relay 1",
      "Relay 2",
      "Relay 3",
      "Relay 4",
      "Компресор",
    ]);
    const relay1 = lanes[0];
    expect(relay1.intervals.map((entry) => entry.state)).toEqual(["on", "off"]);
    const comp = lanes.at(-1)!;
    expect(comp.intervals.map((entry) => entry.state)).toContain("unknown");
    expect(
      buildDashboardStateLanes(series, undefined, domain).every((lane) => lane.intervals.length === 0),
    ).toBe(true);
  });

  it("removes digital channels from the numeric chart", () => {
    const groups = buildSavedDashboardChartGroups({
      dashboardId: "d",
      series: series.map((entry) => ({ ...entry, history: [] })),
      status: "live",
      xDomain: domain,
    });
    const plotted = groups.flatMap((group) => group.scene.series.map((entry) => entry.identity.metric));
    expect(plotted).toEqual(["temperature.probe"]);
  });

  it("renders lanes with text states, the legend and the shared cursor state", () => {
    const lanes = buildDashboardStateLanes(series, (identity) => store.get(identity), domain);
    render(
      <DashboardStateLanes lanes={lanes} fromMs={domain.fromMs} toMs={domain.toMs} cursorMs={T0 + 25_000} />,
    );
    expect(screen.getByTestId("dashboard-state-lanes")).toHaveTextContent("Немає даних (порожньо)");
    const cursorStates = screen.getAllByTestId("state-lane-cursor-state").map((node) => node.textContent);
    expect(cursorStates).toContain("ON"); // relay 2 is on at +25 s
    expect(cursorStates).toContain("OFF"); // relay 1 is off at +25 s
    expect(screen.getAllByLabelText(/Компресор .* Невідомо/).length).toBeGreaterThan(0);
  });
});

describe("StateLaneRow", () => {
  it("shows an explicit NO DATA label for an empty lane and never colour-only states", () => {
    render(
      <StateLaneRow
        label="Компресор"
        onMeaning="працює"
        intervals={[]}
        fromMs={0}
        toMs={1000}
        cursorMs={500}
      />,
    );
    expect(screen.getByText("Немає даних", { selector: "span.absolute" })).toBeInTheDocument();
    expect(screen.getByTestId("state-lane-cursor-state")).toHaveTextContent("Немає даних");
  });
});
