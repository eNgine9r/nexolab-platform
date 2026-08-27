import { describe, expect, it } from "vitest";

import { buildEnergyCadenceAuthority } from "./energy-cadence-authority";

const basePayload = {
  schema_version: 2,
  revision: 3,
  updated_at: "2026-08-03T10:03:00.000Z",
  devices: [
    {
      device_id: "le01mp-200",
      bus_id: "rs485-main",
      device_family: "le01mp",
      unit_id: 200,
      effective_interval_seconds: 10,
    },
  ],
  cadence: {
    family_defaults: [{ bus_id: "rs485-main", device_family: "le01mp", interval_seconds: 60 }],
    device_overrides: [{ device_id: "le01mp-200", interval_seconds: 10 }],
  },
  recent_audit: [
    {
      revision: 3,
      actor: "operator",
      reason: "faster meter cadence",
      changed_at: "2026-08-03T10:03:00.000Z",
      changes: [
        {
          entity: "cadence_device_override",
          id: "le01mp-200",
          from: "inherited:60.0",
          to: "10.0",
        },
      ],
    },
    {
      revision: 2,
      actor: "operator",
      reason: "slower family cadence",
      changed_at: "2026-08-03T10:01:00.000Z",
      changes: [
        {
          entity: "cadence_family_default",
          id: "rs485-main/le01mp",
          from: "30.0",
          to: "60.0",
        },
      ],
    },
    {
      revision: 1,
      actor: "system:migration",
      reason: "bootstrap",
      changed_at: "2026-08-03T10:00:00.000Z",
      changes: [
        {
          entity: "cadence_family_default",
          id: "rs485-main/le01mp",
          from: "legacy_priority_policy",
          to: "30.0",
        },
      ],
    },
  ],
};

describe("energy cadence authority", () => {
  it("reconstructs persisted cadence regimes from current policy and reverse audit", () => {
    const authority = buildEnergyCadenceAuthority(basePayload);

    expect(authority).not.toBeNull();
    expect(authority!.intervalMsAt(200, Date.parse("2026-08-03T10:00:30Z"))).toBe(30_000);
    expect(authority!.intervalMsAt(200, Date.parse("2026-08-03T10:02:00Z"))).toBe(60_000);
    expect(authority!.intervalMsAt(200, Date.parse("2026-08-03T10:04:00Z"))).toBe(10_000);
  });

  it("integrates cadence time on both sides of a persisted transition boundary", () => {
    const authority = buildEnergyCadenceAuthority(basePayload)!;

    expect(
      authority.maximumSourceGapMs(
        200,
        Date.parse("2026-08-03T10:00:50Z"),
        Date.parse("2026-08-03T10:01:50Z"),
      ),
    ).toBe(170_000);
    expect(
      authority.maximumSourceGapMs(
        200,
        Date.parse("2026-08-03T10:02:50Z"),
        Date.parse("2026-08-03T10:04:50Z"),
      ),
    ).toBeCloseTo(38_333.333, 3);
    expect(
      authority.maximumSourceGapMs(
        200,
        Date.parse("2026-08-03T10:03:10Z"),
        Date.parse("2026-08-03T10:03:20Z"),
      ),
    ).toBe(30_000);
  });

  it("fails safe before the oldest retained audit instead of projecting current cadence backward", () => {
    const payload = {
      ...basePayload,
      revision: 23,
      recent_audit: basePayload.recent_audit.slice(0, 2).map((item, index) => ({
        ...item,
        revision: 23 - index,
      })),
    };
    const authority = buildEnergyCadenceAuthority(payload)!;

    expect(authority.intervalMsAt(200, Date.parse("2026-08-03T10:00:30Z"))).toBeNull();
    expect(authority.intervalMsAt(200, Date.parse("2026-08-03T10:02:00Z"))).toBe(60_000);
  });

  it("keeps current cadence authoritative after updated_at when audit is unavailable", () => {
    const authority = buildEnergyCadenceAuthority({ ...basePayload, recent_audit: [] })!;

    expect(authority.intervalMsAt(200, Date.parse("2026-08-03T10:02:59Z"))).toBeNull();
    expect(authority.intervalMsAt(200, Date.parse("2026-08-03T10:03:01Z"))).toBe(10_000);
  });

  it("rejects malformed registry authority instead of fabricating a policy", () => {
    expect(buildEnergyCadenceAuthority({ ...basePayload, cadence: null })).toBeNull();
    expect(buildEnergyCadenceAuthority({ ...basePayload, updated_at: "not-a-time" })).toBeNull();
  });
});
