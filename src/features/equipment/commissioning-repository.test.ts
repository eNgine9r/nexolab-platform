import { describe, expect, it, vi } from "vitest";

import { HttpCommissioningRepository, type CommissioningSessionWrite } from "./commissioning-repository";

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
