import { describe, expect, it, vi } from "vitest";

import {
  CANONICAL_PROPERTY_PROVIDER_PROFILE,
  HttpRefrigerationCircuitConfigurationRepository,
} from "./circuit-configuration-repository";

const at = new Date("2026-09-18T10:00:00.000Z");

function json(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function circuit(id: string, equipmentId = "equipment-1", name = id) {
  return {
    id,
    equipment_id: equipmentId,
    business_key: `key-${id}`,
    display_name: name,
    created_by: "operator",
    created_at: "2026-09-18T09:00:00Z",
  };
}

function lifecycle(state = "active") {
  return {
    id: "lifecycle-1",
    circuit_id: "circuit-1",
    state,
    calculation_enabled: state === "active",
    valid_from: "2026-09-18T09:00:00Z",
    valid_to: null,
    revision: 1,
    recorded_by: "operator",
    recorded_at: "2026-09-18T09:00:00Z",
  };
}

function configuration() {
  return {
    id: "config-1",
    circuit_id: "circuit-1",
    schema_version: "refrigeration-circuit-configuration/v1",
    refrigerant_code: "R290",
    calculation_policy_version: "lab-v1",
    property_provider_profile: CANONICAL_PROPERTY_PROVIDER_PROFILE,
    valid_from: "2026-09-18T09:00:00Z",
    valid_to: null,
    revision: 1,
    recorded_by: "operator",
    recorded_at: "2026-09-18T09:00:00Z",
  };
}

function binding() {
  return {
    id: "binding-1",
    circuit_id: "circuit-1",
    signal_id: "signal-1",
    role: "suction_pressure",
    physical_quantity: "pressure",
    engineering_unit: "bar",
    instrument_kind: "pressure_transmitter",
    pressure_reference: "gauge",
    valid_from: "2026-09-18T09:00:00Z",
    valid_to: null,
    revision: 1,
    recorded_by: "operator",
    recorded_at: "2026-09-18T09:00:00Z",
    ended_by: null,
    ended_at: null,
  };
}

describe("HttpRefrigerationCircuitConfigurationRepository", () => {
  it("filters and sorts organization circuits for the current equipment", async () => {
    const fetchImpl = vi.fn(async () =>
      json({
        items: [
          circuit("b", "equipment-1", "Zulu"),
          circuit("foreign", "equipment-2", "Other"),
          circuit("a", "equipment-1", "Alpha"),
        ],
      }),
    );
    const repository = new HttpRefrigerationCircuitConfigurationRepository(
      "http://127.0.0.1:8082",
      fetchImpl as unknown as typeof fetch,
    );

    const rows = await repository.listCircuits("equipment-1");

    expect(rows.map((row) => row.id)).toEqual(["a", "b"]);
    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:8082/api/v1/refrigeration/circuits",
      expect.objectContaining({ method: "GET", credentials: "same-origin" }),
    );
  });

  it("sends explicit append-only circuit, lifecycle and configuration payloads", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(json(circuit("circuit-1"), 201))
      .mockResolvedValueOnce(json(lifecycle("inactive"), 201))
      .mockResolvedValueOnce(json(configuration(), 201));
    const repository = new HttpRefrigerationCircuitConfigurationRepository(
      "http://127.0.0.1:8082",
      fetchImpl as unknown as typeof fetch,
    );

    await repository.createCircuit({
      equipmentId: "equipment-1",
      businessKey: "main",
      displayName: "Основний контур",
      initialState: "active",
      validFrom: at,
    });
    await repository.appendLifecycle("circuit-1", { state: "inactive", validFrom: at });
    await repository.appendConfiguration("circuit-1", {
      refrigerantCode: "R290",
      calculationPolicyVersion: "lab-v1",
      propertyProviderProfile: CANONICAL_PROPERTY_PROVIDER_PROFILE,
      validFrom: at,
    });

    expect(JSON.parse(String(fetchImpl.mock.calls[0]?.[1]?.body))).toEqual({
      equipment_id: "equipment-1",
      business_key: "main",
      display_name: "Основний контур",
      initial_state: "active",
      valid_from: at.toISOString(),
    });
    expect(JSON.parse(String(fetchImpl.mock.calls[1]?.[1]?.body))).toEqual({
      state: "inactive",
      valid_from: at.toISOString(),
    });
    expect(JSON.parse(String(fetchImpl.mock.calls[2]?.[1]?.body))).toEqual({
      schema_version: "refrigeration-circuit-configuration/v1",
      refrigerant_code: "R290",
      calculation_policy_version: "lab-v1",
      property_provider_profile: CANONICAL_PROPERTY_PROVIDER_PROFILE,
      valid_from: at.toISOString(),
    });
  });

  it("uses canonical binding-candidate discovery and still posts explicit binding authority", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(
        json({
          items: [
            {
              signal_id: "signal-1",
              instrument_id: "instrument-1",
              signal_display_name: "Suction pressure",
              instrument_display_name: "PT-1",
              physical_quantity: "pressure",
              engineering_unit: "bar",
              instrument_kind: "pressure_transmitter",
              pressure_reference: "gauge",
            },
          ],
        }),
      )
      .mockResolvedValueOnce(json(binding(), 201))
      .mockResolvedValueOnce(
        json(
          {
            ...binding(),
            valid_to: at.toISOString(),
            ended_by: "operator",
            ended_at: at.toISOString(),
          },
          200,
        ),
      );
    const repository = new HttpRefrigerationCircuitConfigurationRepository(
      "http://127.0.0.1:8082",
      fetchImpl as unknown as typeof fetch,
    );

    const candidates = await repository.listBindingCandidates("suction_pressure", at);
    await repository.appendBinding("circuit-1", {
      role: "suction_pressure",
      signalId: candidates[0].signalId,
      validFrom: at,
    });
    await repository.endBinding("circuit-1", "suction_pressure", at);

    expect(candidates[0]).toMatchObject({
      signalId: "signal-1",
      pressureReference: "gauge",
      engineeringUnit: "bar",
    });
    expect(String(fetchImpl.mock.calls[0]?.[0])).toContain(
      "/api/v1/refrigeration/circuits/binding-candidates?",
    );
    expect(String(fetchImpl.mock.calls[0]?.[0])).toContain("role=suction_pressure");
    expect(JSON.parse(String(fetchImpl.mock.calls[1]?.[1]?.body))).toEqual({
      role: "suction_pressure",
      signal_id: "signal-1",
      valid_from: at.toISOString(),
    });
    expect(JSON.parse(String(fetchImpl.mock.calls[2]?.[1]?.body))).toEqual({
      valid_to: at.toISOString(),
    });
  });

  it("parses policy authority without inventing defaults", async () => {
    const fetchImpl = vi.fn(async () =>
      json({
        items: [
          {
            id: "policy-1",
            schema_version: "refrigeration-calculation-policy/v1",
            version: "lab-v1",
            maximum_age_ms: 30000,
            maximum_future_clock_skew_ms: 1000,
            maximum_cross_input_skew_ms: 5000,
            calibration_vocabulary_version: "calibration-state/v1",
            accepted_calibration_states: ["valid"],
            require_calibration_at_observation: true,
            calibration_required_roles: ["suction_pressure"],
            created_by: "operator",
            created_at: "2026-09-18T09:00:00Z",
          },
        ],
      }),
    );
    const repository = new HttpRefrigerationCircuitConfigurationRepository(
      "http://127.0.0.1:8082",
      fetchImpl as unknown as typeof fetch,
    );

    const policies = await repository.listPolicies();

    expect(policies).toEqual([
      expect.objectContaining({
        version: "lab-v1",
        maximumAgeMs: 30000,
        acceptedCalibrationStates: ["valid"],
        requireCalibrationAtObservation: true,
      }),
    ]);
  });

  it("fails closed on malformed contracts and surfaces backend conflict messages", async () => {
    const malformed = new HttpRefrigerationCircuitConfigurationRepository(
      "http://127.0.0.1:8082",
      vi.fn(async () => json({ items: [{ id: "broken" }] })) as unknown as typeof fetch,
    );
    await expect(malformed.listCircuits("equipment-1")).rejects.toThrow("некоректний контракт");

    const conflict = new HttpRefrigerationCircuitConfigurationRepository(
      "http://127.0.0.1:8082",
      vi.fn(async () =>
        json(
          {
            detail: {
              code: "refrigeration_circuit_history_order_conflict",
              message: "effective timestamp must increase",
            },
          },
          409,
        ),
      ) as unknown as typeof fetch,
    );
    await expect(conflict.appendLifecycle("circuit-1", { state: "retired", validFrom: at })).rejects.toThrow(
      "effective timestamp must increase",
    );
  });
});
