import { describe, expect, it, vi } from "vitest";

import {
  createCommissioningIdempotencyKey,
  HttpCommissioningRepository,
  type CommissioningSessionWrite,
} from "./commissioning-repository";

const profilePayload = {
  id: "embraco-sync",
  version: "embraco-sync-fc03-v1.00.04",
  device_family: "embraco",
  device_class: "temperature-controller",
  manufacturer: "Embraco",
  models: ["Sync"],
  display_name: "Embraco Sync",
  transport_kind: "modbus_rtu",
  capability_status: "repository_supported_hardware_evidenced",
  evidence_note: "Existing strict FC03-only contract.",
  read_only: true,
};

const sessionPayload = {
  id: "commissioning-1",
  lifecycle: "draft",
  device_class: "temperature-controller",
  manufacturer: "Embraco",
  model: "Sync",
  profile_id: "embraco-sync",
  profile_version: "embraco-sync-fc03-v1.00.04",
  transport_kind: "modbus_rtu",
  node_id: null,
  bus_id: null,
  stable_transport_identifier: null,
  unit_id: null,
  ip_address: null,
  target_equipment_key: null,
  blocked_reason: null,
  unsupported_reason: null,
  version: 1,
  created_by: "operator",
  updated_by: "operator",
  created_at: "2026-09-01T12:00:00Z",
  updated_at: "2026-09-01T12:00:00Z",
  cancelled_at: null,
};

const preflightPayload = {
  id: "preflight-1",
  session_id: "commissioning-1",
  session_version: 2,
  state: "completed",
  result: "passed",
  code: "preflight_passed",
  evidence_level: "hardware_verified",
  evidence: {
    schema_version: 1,
    result: "passed",
    code: "preflight_passed",
    evidence_level: "hardware_verified",
    node_id: "edge-01",
    bus_id: "rs485-main",
    stable_transport_identifier: "/dev/serial/by-id/usb-test",
    unit_id: 2,
    profile_id: "embraco-sync",
    profile_version: "embraco-sync-fc03-v1.00.04",
    read_method: "modbus_rtu_fc03",
    function_codes: [3],
    checks: [{ key: "write_safety", state: "passed", detail: "writes none" }],
    observations: [{ key: "control_state", quality: "valid", semantic: "cooling" }],
    warnings: [],
    duration_ms: 12,
    modbus_writes: "none",
    hardware_writes: "none",
  },
  actor_subject: "operator",
  started_at: "2026-09-02T08:00:00Z",
  completed_at: "2026-09-02T08:00:01Z",
};

const activationPlanPayload = {
  schema_version: 1,
  session_id: "commissioning-1",
  session_version: 2,
  preflight_attempt_id: "preflight-1",
  preflight_completed_at: "2026-09-02T08:00:01Z",
  preflight_evidence_level: "hardware_verified",
  device_class: "temperature-controller",
  manufacturer: "Embraco",
  model: "Sync",
  profile_id: "embraco-sync",
  profile_version: "embraco-sync-fc03-v1.00.04",
  device_family: "embraco",
  node_id: "edge-01",
  bus_id: "rs485-embraco",
  stable_transport_identifier: "/dev/serial/by-id/usb-embraco",
  unit_id: 2,
  target_equipment_key: "equipment-1",
  telemetry_source: "embraco-sync",
  telemetry_equipment_id: "EMBRACO-2",
  polling_mode: "read_only_fc03",
  binding_kind: "refrigeration_controller",
  warnings: [],
  will_not_perform: ["Modbus FC05/06/15/16 writes", "controller parameter changes"],
};

const activationPayload = {
  id: "activation-1",
  session_id: "commissioning-1",
  preflight_attempt_id: "preflight-1",
  session_version: 2,
  state: "active",
  plan: activationPlanPayload,
  evidence: { modbus_writes: "none", hardware_writes: "none" },
  actor_subject: "operator",
  started_at: "2026-09-02T08:01:00Z",
  completed_at: "2026-09-02T08:01:02Z",
};

const draft: CommissioningSessionWrite = {
  deviceClass: "temperature-controller",
  manufacturer: "Embraco",
  model: "Sync",
  profileId: "embraco-sync",
  nodeId: null,
  busId: null,
  stableTransportIdentifier: null,
  unitId: null,
  ipAddress: null,
  targetEquipmentKey: null,
};

describe("HttpCommissioningRepository", () => {
  it("creates an idempotency key when randomUUID is unavailable on controlled HTTP", () => {
    const key = createCommissioningIdempotencyKey({
      getRandomValues(bytes) {
        return bytes.fill(0xab);
      },
    });

    expect(key).toBe(`commissioning-${"ab".repeat(16)}`);
  });

  it("parses the repository-owned profile and persisted session lists", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(json({ items: [profilePayload] }))
      .mockResolvedValueOnce(json({ items: [sessionPayload] }));
    const repository = new HttpCommissioningRepository({
      apiBaseUrl: "http://telemetry.local/",
      fetchImpl,
    });

    await expect(repository.listProfiles()).resolves.toMatchObject([
      {
        id: "embraco-sync",
        capabilityStatus: "repository_supported_hardware_evidenced",
        readOnly: true,
      },
    ]);
    await expect(repository.listSessions()).resolves.toMatchObject([
      { id: "commissioning-1", lifecycle: "draft", version: 1 },
    ]);
  });

  it("sends idempotency, optimistic concurrency and audit headers for mutations", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(json(sessionPayload, 201))
      .mockResolvedValueOnce(json({ ...sessionPayload, version: 2 }))
      .mockResolvedValueOnce(
        json({ ...sessionPayload, lifecycle: "cancelled", version: 3, cancelled_at: "2026-09-01T13:00:00Z" }),
      );
    const repository = new HttpCommissioningRepository({
      apiBaseUrl: "http://telemetry.local",
      fetchImpl,
    });

    await repository.createSession(draft, "intent-1");
    await repository.updateSession("commissioning-1", { unitId: 2 }, 1);
    await repository.cancelSession("commissioning-1", 2);

    expect(fetchImpl.mock.calls[0]?.[1]?.headers).toMatchObject({
      "Idempotency-Key": "intent-1",
      "X-Audit-Reason": "Create operator commissioning draft",
    });
    expect(fetchImpl.mock.calls[1]?.[1]?.headers).toMatchObject({
      "If-Match": 'W/"commissioning-session-v1"',
      "X-Audit-Reason": "Update operator commissioning draft",
    });
    expect(fetchImpl.mock.calls[2]?.[1]?.headers).toMatchObject({
      "If-Match": 'W/"commissioning-session-v2"',
      "X-Audit-Reason": "Cancel operator commissioning draft",
    });
  });

  it("parses persisted preflight evidence and sends bounded mutation headers", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(json(preflightPayload))
      .mockResolvedValueOnce(json(preflightPayload));
    const repository = new HttpCommissioningRepository({
      apiBaseUrl: "http://telemetry.local",
      fetchImpl,
    });

    await expect(repository.getLatestPreflight("commissioning-1")).resolves.toMatchObject({
      id: "preflight-1",
      evidenceLevel: "hardware_verified",
      evidence: {
        readMethod: "modbus_rtu_fc03",
        functionCodes: [3],
        modbusWrites: "none",
        hardwareWrites: "none",
      },
    });
    await repository.runPreflight("commissioning-1", 2, "preflight-key-1");

    expect(fetchImpl.mock.calls[1]?.[1]?.headers).toMatchObject({
      "If-Match": 'W/"commissioning-session-v2"',
      "Idempotency-Key": "preflight-key-1",
      "X-Audit-Reason": "Run bounded read-only commissioning preflight",
    });
  });

  it("parses activation plan/evidence and sends exact optimistic activation headers", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(json(activationPlanPayload))
      .mockResolvedValueOnce(json(activationPayload))
      .mockResolvedValueOnce(json(activationPayload));
    const repository = new HttpCommissioningRepository({
      apiBaseUrl: "http://telemetry.local",
      fetchImpl,
    });

    await expect(repository.getActivationPlan("commissioning-1")).resolves.toMatchObject({
      pollingMode: "read_only_fc03",
      bindingKind: "refrigeration_controller",
      willNotPerform: ["Modbus FC05/06/15/16 writes", "controller parameter changes"],
    });
    await expect(repository.getLatestActivation("commissioning-1")).resolves.toMatchObject({
      id: "activation-1",
      state: "active",
      evidence: { modbus_writes: "none", hardware_writes: "none" },
    });
    await repository.runActivation("commissioning-1", 2, "activation-key-1");

    expect(fetchImpl.mock.calls[2]?.[1]?.headers).toMatchObject({
      "If-Match": 'W/"commissioning-session-v2"',
      "Idempotency-Key": "activation-key-1",
      "X-Audit-Reason": "Activate verified read-only commissioning monitoring",
    });
  });

  it("surfaces deterministic backend error codes", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      json(
        {
          detail: {
            code: "commissioning_session_version_conflict",
            message: "stale version",
          },
        },
        409,
      ),
    );
    const repository = new HttpCommissioningRepository({
      apiBaseUrl: "http://telemetry.local",
      fetchImpl,
    });

    await expect(repository.updateSession("commissioning-1", { unitId: 2 }, 1)).rejects.toMatchObject({
      code: "commissioning_session_version_conflict",
      status: 409,
    });
  });
});

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
