import { describe, expect, it } from "vitest";

import type { CompressorRuntimeDuty } from "./compressor-runtime";
import { buildControllerAnalysisCsv, controllerAnalysisCsvFilename } from "./controller-history-export";
import { EMBRACO_METRICS } from "./controller-monitoring";
import type { RelayTransition } from "./controller-timeline";
import type { TelemetrySample } from "@/lib/telemetry/types";

const fromMs = Date.parse("2026-09-01T07:00:00.000Z");
const toMs = Date.parse("2026-09-01T07:05:00.000Z");
const range = { fromMs, toMs };

function sample(
  eventId: string,
  second: number,
  metric: string,
  value: number,
  channelId: string,
): TelemetrySample {
  return {
    event_id: eventId,
    node_id: "edge-01",
    captured_at: new Date(fromMs + second * 1000).toISOString(),
    metric,
    value,
    unit: metric === EMBRACO_METRICS.compressorSpeed ? "rpm" : "bitfield",
    quality: "valid",
    source: "embraco-sync",
    equipment_id: "EMBRACO-2",
    channel_id: channelId,
    alarm: null,
    raw_value: value,
    raw_status: null,
  };
}

const duty: CompressorRuntimeDuty = {
  status: "available",
  dutyPercent: 62.5,
  coveragePercent: 100,
  runningMs: 187_500,
  observedMs: 300_000,
  requestedMs: 300_000,
  continuityBreaks: 0,
  sourceGapMs: 180_000,
  startCount: 1,
};

describe("controller selected-interval CSV export", () => {
  it("exports KPI summary, decoded relay telemetry and traceable transition/start records", () => {
    const speed0 = sample("speed-0", 0, EMBRACO_METRICS.compressorSpeed, 0, "2-compressor-speed");
    const speed1 = sample("speed-1", 60, EMBRACO_METRICS.compressorSpeed, 4500, "2-compressor-speed");
    const relay0 = sample("relay-0", 0, EMBRACO_METRICS.relays, 0, 'relay,"bits"');
    const relay1 = sample("relay-1", 60, EMBRACO_METRICS.relays, 5, 'relay,"bits"');
    const transitions: RelayTransition[] = [
      {
        relayIndex: 0,
        fromState: false,
        toState: true,
        previousObservedAtMs: fromMs,
        observedAtMs: fromMs + 60_000,
        previousEventId: "relay-0",
        eventId: "relay-1",
      },
    ];
    const csv = buildControllerAnalysisCsv({
      history: new Map([
        [EMBRACO_METRICS.compressorSpeed, [speed0, speed1]],
        [EMBRACO_METRICS.relays, [relay0, relay1]],
      ]),
      range,
      duty,
      compressorStarts: [
        {
          previousObservedAtMs: fromMs,
          observedAtMs: fromMs + 60_000,
          previousValueRpm: 0,
          valueRpm: 4500,
          previousEventId: "speed-0",
          eventId: "speed-1",
        },
      ],
      relayTransitions: transitions,
      equipmentId: "EMBRACO-2",
      timeZone: "Europe/Kyiv",
    });

    expect(csv.startsWith("\uFEFFselected_from_utc")).toBe(true);
    expect(csv).toContain("compressor.runtime_duty");
    expect(csv).toContain("compressor.start_count");
    expect(csv).toContain("Relay 1=ON | Relay 2=OFF | Relay 3=ON | Relay 4=OFF");
    expect(csv).toContain("compressor_start");
    expect(csv).toContain("relay_transition");
    expect(csv).toContain("Пуск зафіксовано");
    expect(csv).toContain('"relay,""bits"""');
    expect(csv).toContain("2026-09-01T07:01:00.000Z");
    expect(csv).toContain("relay-0");
  });

  it("excludes raw telemetry samples outside the selected interval", () => {
    const outside = sample("outside", 360, EMBRACO_METRICS.compressorSpeed, 4500, "speed");
    const inside = sample("inside", 60, EMBRACO_METRICS.compressorSpeed, 0, "speed");
    const csv = buildControllerAnalysisCsv({
      history: new Map([[EMBRACO_METRICS.compressorSpeed, [inside, outside]]]),
      range,
      duty,
      compressorStarts: [],
      relayTransitions: [],
      equipmentId: "EMBRACO-2",
      timeZone: "UTC",
    });
    expect(csv).toContain("inside");
    expect(csv).not.toContain("outside");
  });

  it("neutralizes formula-prefixed telemetry text without changing numeric measurements", () => {
    const hostile = {
      ...sample("formula", 60, EMBRACO_METRICS.compressorSpeed, -12, "=1+1"),
      source: "+CMD",
      equipment_id: "@edge",
      unit: "-formula",
      raw_value: -12,
    };
    const csv = buildControllerAnalysisCsv({
      history: new Map([[EMBRACO_METRICS.compressorSpeed, [hostile]]]),
      range,
      duty,
      compressorStarts: [],
      relayTransitions: [],
      equipmentId: "EMBRACO-2",
      timeZone: "UTC",
    });

    expect(csv).toContain("'=1+1");
    expect(csv).toContain("'+CMD");
    expect(csv).toContain("'@edge");
    expect(csv).toContain("'-formula");
    expect(csv).toContain(",-12,");
  });

  it("produces a deterministic safe filename", () => {
    expect(controllerAnalysisCsvFilename("EMBRACO 2 / Cool jet", range)).toBe(
      "nexolab-EMBRACO-2-Cool-jet-20260901T070000Z-20260901T070500Z.csv",
    );
  });
});

describe("temperature probe export", () => {
  it("exports both raw probes and quality without inventing °C; preserves signed and original raw", () => {
    const cabinet: TelemetrySample = {
      ...sample("cabinet-probe", 60, EMBRACO_METRICS.cabinet, 0, "2-cabinet-temperature"),
      raw_value: 65485,
      value: null,
      unit: "degC",
      quality: "unknown",
    };
    const defrost: TelemetrySample = {
      ...sample("defrost-probe", 120, EMBRACO_METRICS.evaporator, 0, "2-evaporator-temperature"),
      raw_value: 65418,
      value: null,
      unit: "degC",
      quality: "unknown",
    };
    const csv = buildControllerAnalysisCsv({
      history: new Map([
        [EMBRACO_METRICS.cabinet, [cabinet]],
        [EMBRACO_METRICS.evaporator, [defrost]],
      ]),
      range,
      duty,
      compressorStarts: [],
      relayTransitions: [],
      equipmentId: "EMBRACO-2",
      timeZone: "Europe/Kyiv",
    });
    expect(csv).toContain("raw_value,raw_signed,raw_status");
    const cabinetRow = csv.split("\r\n").find((line) => line.includes("cabinet-probe"));
    const defrostRow = csv.split("\r\n").find((line) => line.includes("defrost-probe"));
    expect(cabinetRow).toContain("temperature.cabinet");
    expect(cabinetRow).toContain(",unknown,");
    expect(cabinetRow).toContain(",65485,-51,");
    expect(cabinetRow).toContain("масштаб °C не підтверджений");
    expect(defrostRow).toContain("temperature.evaporator");
    expect(defrostRow).toContain(",65418,-118,");
    expect(defrostRow).toContain("Датчик відтайки");
    // A missing approved conversion must never create an engineering value.
    const headers = csv.split("\r\n")[0]!.replace("\uFEFF", "").split(",");
    const cabinetColumns = cabinetRow!.split(",");
    expect(cabinetColumns[headers.indexOf("value")]).toBe("");
  });

  it("exports calibrated Celsius as valid only when the source sample itself is valid", () => {
    const calibrated: TelemetrySample = {
      ...sample("calibrated", 60, EMBRACO_METRICS.cabinet, -0.51, "2-cabinet-temperature"),
      raw_value: 65485,
      unit: "degC",
      quality: "valid",
    };
    const csv = buildControllerAnalysisCsv({
      history: new Map([[EMBRACO_METRICS.cabinet, [calibrated]]]),
      range,
      duty,
      compressorStarts: [],
      relayTransitions: [],
      equipmentId: "EMBRACO-2",
      timeZone: "UTC",
    });
    expect(csv).toContain("temperature.cabinet");
    expect(csv).toContain(",-0.51,degC,valid,");
    expect(csv).toContain("підтверджене значення °C");
  });
});
