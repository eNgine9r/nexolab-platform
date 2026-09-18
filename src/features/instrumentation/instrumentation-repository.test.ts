import { describe, expect, it, vi } from "vitest";

import {
  HttpInstrumentationRegistryRepository,
  instrumentEtag,
  signalEtag,
} from "./instrumentation-repository";

const instrumentPayload = {
  id: "instrument-1",
  inventory_key: "PT-001",
  display_name: "Suction pressure transmitter",
  instrument_kind: "pressure_transmitter",
  manufacturer: "Emerson",
  model: "PT5N-30M",
  serial_number: "SN-001",
  pressure_reference: "gauge",
  lifecycle_state: "active",
  metadata: {},
  version: 3,
  created_by: "operator",
  updated_by: "operator",
  created_at: "2026-09-18T10:00:00Z",
  updated_at: "2026-09-18T10:05:00Z",
};

const signalPayload = {
  id: "signal-1",
  instrument_id: "instrument-1",
  business_key: "pressure",
  display_name: "Suction pressure",
  physical_quantity: "pressure",
  engineering_unit: "bar",
  lifecycle_state: "active",
  metadata: {},
  version: 2,
  created_by: "operator",
  updated_by: "operator",
  created_at: "2026-09-18T10:00:00Z",
  updated_at: "2026-09-18T10:05:00Z",
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("HttpInstrumentationRegistryRepository", () => {
  it("strictly parses the canonical Instrument list", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({ items: [instrumentPayload] }));
    const repository = new HttpInstrumentationRegistryRepository("http://nexolab.local:8082/", fetchImpl);

    const items = await repository.listInstruments();

    expect(items).toEqual([
      expect.objectContaining({
        id: "instrument-1",
        inventoryKey: "PT-001",
        instrumentKind: "pressure_transmitter",
        pressureReference: "gauge",
        lifecycleState: "active",
        version: 3,
      }),
    ]);
    expect(fetchImpl).toHaveBeenCalledWith(
      "http://nexolab.local:8082/api/v1/instrumentation/instruments",
      expect.objectContaining({ method: "GET", credentials: "same-origin" }),
    );
  });

  it("creates an Instrument without inventing hidden metadata or acceptance", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(instrumentPayload, 201));
    const repository = new HttpInstrumentationRegistryRepository("http://nexolab.local:8082", fetchImpl);

    await repository.createInstrument({
      inventoryKey: " PT-001 ",
      displayName: " Suction pressure transmitter ",
      instrumentKind: "pressure_transmitter",
      manufacturer: " Emerson ",
      model: "PT5N-30M",
      serialNumber: "SN-001",
      pressureReference: "gauge",
      lifecycleState: "active",
    });

    const [, init] = fetchImpl.mock.calls[0] ?? [];
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("X-Audit-Reason")).toBe("Created from Instrumentation Registry");
    expect(JSON.parse(String(init?.body))).toEqual({
      inventory_key: "PT-001",
      display_name: "Suction pressure transmitter",
      instrument_kind: "pressure_transmitter",
      manufacturer: "Emerson",
      model: "PT5N-30M",
      serial_number: "SN-001",
      pressure_reference: "gauge",
      lifecycle_state: "active",
      metadata: {},
    });
  });

  it("uses optimistic concurrency for Instrument and Signal updates", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(instrumentPayload))
      .mockResolvedValueOnce(jsonResponse(signalPayload));
    const repository = new HttpInstrumentationRegistryRepository("http://nexolab.local:8082", fetchImpl);

    await repository.updateInstrument(
      "instrument-1",
      {
        inventoryKey: "PT-001",
        displayName: "Suction pressure transmitter",
        instrumentKind: "pressure_transmitter",
        manufacturer: "Emerson",
        model: "PT5N-30M",
        serialNumber: "SN-001",
        pressureReference: "gauge",
        lifecycleState: "active",
      },
      3,
    );
    await repository.updateSignal(
      "instrument-1",
      "signal-1",
      {
        businessKey: "pressure",
        displayName: "Suction pressure",
        physicalQuantity: "pressure",
        engineeringUnit: "bar",
        lifecycleState: "active",
      },
      2,
    );

    expect(new Headers(fetchImpl.mock.calls[0]?.[1]?.headers).get("If-Match")).toBe(instrumentEtag(3));
    expect(new Headers(fetchImpl.mock.calls[1]?.[1]?.headers).get("If-Match")).toBe(signalEtag(2));
  });

  it("appends explicit calculation acceptance with an effective timestamp", async () => {
    const acceptance = {
      id: "acceptance-1",
      instrument_id: "instrument-1",
      schema_version: "acceptance-state/v1",
      accepted_for_calculation: true,
      state_label: "lab-approved",
      effective_from: "2026-09-18T10:30:00Z",
      effective_to: null,
      revision: 1,
      recorded_by: "operator",
      recorded_at: "2026-09-18T10:31:00Z",
    };
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(acceptance, 201));
    const repository = new HttpInstrumentationRegistryRepository("http://nexolab.local:8082", fetchImpl);

    const result = await repository.appendAcceptance("instrument-1", {
      acceptedForCalculation: true,
      effectiveFrom: new Date("2026-09-18T10:30:00Z"),
      stateLabel: "lab-approved",
    });

    expect(result.acceptedForCalculation).toBe(true);
    expect(JSON.parse(String(fetchImpl.mock.calls[0]?.[1]?.body))).toEqual({
      accepted_for_calculation: true,
      effective_from: "2026-09-18T10:30:00.000Z",
      state_label: "lab-approved",
    });
  });

  it("surfaces backend optimistic-concurrency details instead of overwriting", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(
        {
          detail: {
            code: "instrument_version_conflict",
            message: "instrument version conflict",
            expected_version: 3,
            actual_version: 4,
          },
        },
        409,
      ),
    );
    const repository = new HttpInstrumentationRegistryRepository("http://nexolab.local:8082", fetchImpl);

    await expect(
      repository.updateInstrument(
        "instrument-1",
        {
          inventoryKey: "PT-001",
          displayName: "Suction pressure transmitter",
          instrumentKind: "pressure_transmitter",
          manufacturer: null,
          model: null,
          serialNumber: null,
          pressureReference: "gauge",
          lifecycleState: "active",
        },
        3,
      ),
    ).rejects.toMatchObject({
      code: "instrument_version_conflict",
      status: 409,
      expectedVersion: 3,
      actualVersion: 4,
    });
  });

  it("fails closed on a malformed canonical response", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse({ items: [{ ...instrumentPayload, version: "3" }] }));
    const repository = new HttpInstrumentationRegistryRepository("http://nexolab.local:8082", fetchImpl);

    await expect(repository.listInstruments()).rejects.toMatchObject({
      code: "invalid_response",
    });
  });
});
