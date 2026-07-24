import { describe, expect, it } from "vitest";

import type { AttributedTelemetrySample, LaboratorySession } from "./types";
import {
  ACTIONS_BY_STATE,
  deriveWorkspaceConnectionState,
  formatDuration,
  isReadOnlySession,
  selectEnergyUnits,
  selectTemperatureSamples,
  sessionElapsedMs,
} from "./view-model";

const session: LaboratorySession = {
  id: "session-1",
  session_number: "NXL-001",
  node_id: "edge-01",
  state: "running",
  title: "Test",
  customer: null,
  test_object: "Display case",
  model: null,
  serial_number: null,
  standard: null,
  method: null,
  operator_id: null,
  responsible_engineer_id: null,
  metadata_payload: {},
  current_stage_id: null,
  active_config_snapshot_id: "snapshot-1",
  active_limit_version: 1,
  lock_version: 1,
  prepared_at: null,
  started_at: "2026-07-24T10:00:00Z",
  paused_at: null,
  completed_at: null,
  cancelled_at: null,
  archived_at: null,
  created_at: "2026-07-24T09:00:00Z",
  updated_at: "2026-07-24T10:00:00Z",
};

function sample(overrides: Partial<AttributedTelemetrySample>): AttributedTelemetrySample {
  return {
    event_id: "event-1",
    node_id: "edge-01",
    captured_at: "2026-07-24T10:00:10Z",
    metric: "temperature.probe",
    value: 4.2,
    unit: "degC",
    quality: "valid",
    source: "device-agent",
    equipment_id: "K106",
    channel_id: "106-03",
    alarm: null,
    raw_value: 42,
    raw_status: null,
    received_at: "2026-07-24T10:00:11Z",
    session_id: "session-1",
    stage_id: null,
    binding_id: "binding-1",
    config_snapshot_id: "snapshot-1",
    resolver_version: "v1",
    ...overrides,
  };
}

describe("session view model", () => {
  it("maps lifecycle actions and completed read-only state", () => {
    expect(ACTIONS_BY_STATE.running).toEqual(["pause", "complete", "cancel"]);
    expect(isReadOnlySession({ ...session, state: "completed" })).toBe(true);
    expect(isReadOnlySession(session)).toBe(false);
  });

  it("calculates elapsed time deterministically", () => {
    expect(sessionElapsedMs(session, new Date("2026-07-24T11:02:03Z").getTime())).toBe(3_723_000);
    expect(formatDuration(3_723_000)).toBe("01:02:03");
  });

  it("distinguishes live, stale and offline cached snapshots", () => {
    const samples = [sample({ captured_at: "2026-07-24T10:00:00Z" })];

    expect(
      deriveWorkspaceConnectionState({
        loading: false,
        error: null,
        hasSnapshot: true,
        samples,
        now: new Date("2026-07-24T10:00:10Z").getTime(),
      }),
    ).toBe("live");
    expect(
      deriveWorkspaceConnectionState({
        loading: false,
        error: null,
        hasSnapshot: true,
        samples,
        now: new Date("2026-07-24T10:01:00Z").getTime(),
      }),
    ).toBe("stale");
    expect(
      deriveWorkspaceConnectionState({
        loading: false,
        error: new Error("network"),
        hasSnapshot: true,
        samples,
      }),
    ).toBe("offline");
  });

  it("selects the fixed M4 temperature and LE-01MP series", () => {
    const samples = [
      sample({ channel_id: "106-03", value: 3.7 }),
      sample({ event_id: "event-2", channel_id: "106-04", value: 4.1 }),
      sample({
        event_id: "event-3",
        equipment_id: "LE01MP-200",
        channel_id: "200-active-power",
        metric: "electrical.power.active",
        value: 920,
        unit: "W",
      }),
    ];

    expect(selectTemperatureSamples(samples).map((item) => item.sample?.value)).toEqual([3.7, 4.1]);
    expect(selectEnergyUnits(samples)[0].activePower).toBe(920);
  });
});
