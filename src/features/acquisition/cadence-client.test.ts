import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ authenticatedFetch: vi.fn() }));

vi.mock("@/features/security/security-session", () => ({
  createAuthenticatedFetch: () => mocks.authenticatedFetch,
}));

vi.mock("@/features/security/supabase-auth", () => ({
  createRuntimeCredentialProvider: () => ({ getCredential: vi.fn() }),
}));

import { CadenceClientError, createCadenceClient, normalizeCadenceConfiguration } from "./cadence-client";

function payload(revision = 7, xjpInterval = 60) {
  return {
    schema_version: 1,
    registry_revision: revision,
    updated_at: "2026-08-22T17:00:00+00:00",
    policy: {
      presets_seconds: [10, 30, 60],
      custom_min_seconds: 10,
      maximum_seconds: 3600,
      family_defaults: [
        { bus_id: "rs485-main", device_family: "xjp60d", interval_seconds: xjpInterval },
        { bus_id: "rs485-main", device_family: "le01mp", interval_seconds: 30 },
      ],
      device_overrides: [],
    },
    effective_devices: [
      {
        device_id: "xjp60d-106",
        bus_id: "rs485-main",
        device_family: "xjp60d",
        lifecycle: "active",
        effective_interval_seconds: xjpInterval,
        cadence_source: "family_default",
      },
    ],
    capacity: {
      schema_version: 1,
      model: "heterogeneous_device_utilization_v1",
      safe: true,
      maximum_allowed_utilization_percent: 75,
      safety_margin_percent: 25,
      buses: [
        {
          bus_id: "rs485-main",
          safe: true,
          active_device_count: 1,
          active_target_count: 2,
          estimated_utilization_percent: 18.5,
          maximum_allowed_utilization_percent: 75,
          recommended_minimum_interval_seconds: null,
          request_budget_source: "serial_timeout_fallback",
        },
      ],
    },
  };
}

describe("acquisition cadence client", () => {
  beforeEach(() => {
    mocks.authenticatedFetch.mockReset();
  });

  it("normalizes only the sanitized persisted device-scoped contract", () => {
    const normalized = normalizeCadenceConfiguration(payload());

    expect(normalized.registryRevision).toBe(7);
    expect(normalized.presetsSeconds).toEqual([10, 30, 60]);
    expect(normalized.familyDefaults[0]).toEqual({
      busId: "rs485-main",
      deviceFamily: "xjp60d",
      intervalSeconds: 60,
    });
    expect(normalized.effectiveDevices[0]).toMatchObject({
      deviceId: "xjp60d-106",
      effectiveIntervalSeconds: 60,
      cadenceSource: "family_default",
    });
    expect(normalized.capacity.buses[0].estimatedUtilizationPercent).toBe(18.5);
  });

  it("re-reads canonical state after a successful mutation instead of trusting PUT response", async () => {
    mocks.authenticatedFetch
      .mockResolvedValueOnce(Response.json(payload(8, 30)))
      .mockResolvedValueOnce(Response.json(payload(9, 30)));
    const client = createCadenceClient("33333333-3333-3333-3333-333333333333");

    const result = await client.mutate({
      expected_revision: 7,
      reason: "Operator updated xjp60d physical polling cadence in NEXOLAB Settings",
      family_defaults: [{ bus_id: "rs485-main", device_family: "xjp60d", interval_seconds: 30 }],
    });

    expect(mocks.authenticatedFetch).toHaveBeenCalledTimes(2);
    expect(mocks.authenticatedFetch.mock.calls[0]?.[1]).toMatchObject({ method: "PUT" });
    expect(mocks.authenticatedFetch.mock.calls[1]?.[1]).toMatchObject({ method: "GET" });
    expect(result.registryRevision).toBe(9);
    expect(result.familyDefaults[0].intervalSeconds).toBe(30);
  });

  it("surfaces capacity rejection with recommendation evidence", async () => {
    mocks.authenticatedFetch.mockResolvedValueOnce(
      Response.json(
        {
          code: "acquisition_capacity_exceeded",
          detail: "Requested acquisition cadence exceeds RS-485 capacity: rs485-main",
          capacity: {
            safe: false,
            maximum_allowed_utilization_percent: 75,
            safety_margin_percent: 25,
            buses: [
              {
                bus_id: "rs485-main",
                safe: false,
                active_device_count: 15,
                active_target_count: 30,
                estimated_utilization_percent: 92.4,
                maximum_allowed_utilization_percent: 75,
                recommended_minimum_interval_seconds: 30,
                request_budget_source: "serial_timeout_fallback",
              },
            ],
          },
        },
        { status: 422 },
      ),
    );
    const client = createCadenceClient(null);

    await expect(
      client.mutate({
        expected_revision: 7,
        reason: "Unsafe acceptance fixture",
        family_defaults: [{ bus_id: "rs485-main", device_family: "xjp60d", interval_seconds: 10 }],
      }),
    ).rejects.toMatchObject({
      code: "acquisition_capacity_exceeded",
      status: 422,
      capacity: {
        safe: false,
        buses: [{ recommendedMinimumIntervalSeconds: 30 }],
      },
    } satisfies Partial<CadenceClientError>);
    expect(mocks.authenticatedFetch).toHaveBeenCalledTimes(1);
  });

  it("turns stale revision into an explicit conflict", async () => {
    mocks.authenticatedFetch.mockResolvedValueOnce(
      Response.json({ detail: "Registry revision conflict" }, { status: 409 }),
    );
    const client = createCadenceClient(null);

    await expect(
      client.mutate({
        expected_revision: 6,
        reason: "Stale acceptance fixture",
        device_overrides: [{ device_id: "xjp60d-106", interval_seconds: 30 }],
      }),
    ).rejects.toMatchObject({ code: "revision_conflict", status: 409 });
    expect(mocks.authenticatedFetch).toHaveBeenCalledTimes(1);
  });
});
