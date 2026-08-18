import { describe, expect, it, vi } from "vitest";

import { VersionManagementClient } from "./version-management";

const snapshot = {
  current: {
    bundle_id: "release-2",
    release: "2.0.0",
    source_commit: "2".repeat(40),
    build_timestamp: "2026-08-13T10:00:00Z",
    runtime_mode: "lan",
    platform: "linux/arm64",
    schema_head: "schema-2",
    deployed_at: "2026-08-13T10:05:00Z",
    health: "ready",
    previous_bundle_id: "release-1",
    previous_release: "1.0.0",
    known_packaged_release: true,
    runtime_state_known: true,
  },
  catalog: [
    {
      bundle_id: "release-2",
      release: "2.0.0",
      source_commit: "2".repeat(40),
      created_at: "2026-08-13T10:00:00Z",
      platform: "linux/arm64",
      schema_head: "schema-2",
      upgrade_from: ["schema-1"],
      runtime_compatible_schema_heads: ["schema-2"],
      manifest_sha256: "a".repeat(64),
      validated: true,
    },
  ],
  history: [],
  active_operation: null,
  rejected_packages: [],
  update_policy: {
    schema_version: 1,
    automatic_updates_enabled: false,
    schedule_local_time: "02:00",
    updated_at: null,
    updated_by: null,
    error_code: null,
  },
  update_check: null,
  offline: true,
  catalog_limit: 20,
};

describe("VersionManagementClient", () => {
  it("parses the offline current-version, catalog and update-policy read model", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(JSON.stringify(snapshot), { status: 200 }));
    const client = new VersionManagementClient("http://127.0.0.1:8082", fetchImpl);

    const result = await client.read();

    expect(result.offline).toBe(true);
    expect(result.current).toMatchObject({ release: "2.0.0", previousBundleId: "release-1" });
    expect(result.catalog[0]).toMatchObject({ bundleId: "release-2", schemaHead: "schema-2" });
    expect(result.updatePolicy).toEqual({
      automaticUpdatesEnabled: false,
      scheduleLocalTime: "02:00",
      updatedAt: null,
      updatedBy: null,
      errorCode: null,
    });
    expect(result.updateCheck).toBeNull();
    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:8082/api/v1/system/version",
      expect.objectContaining({ method: "GET", cache: "no-store" }),
    );
  });

  it("parses durable update-check state without making it installation authority", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          ...snapshot,
          update_check: {
            schema_version: 1,
            status: "completed",
            source: "manual",
            actor: "admin",
            started_at: "2026-08-18T07:00:00Z",
            completed_at: "2026-08-18T07:00:03Z",
            result_code: "candidate_discovered",
            message: "candidate",
            current_commit: "2".repeat(40),
            target_commit: "3".repeat(40),
            candidate_available: true,
            activation_eligible: false,
            blocked_reason: "validated_package_required",
          },
        }),
        { status: 200 },
      ),
    );
    const client = new VersionManagementClient("http://127.0.0.1:8082", fetchImpl);

    const result = await client.read();

    expect(result.updateCheck).toMatchObject({
      resultCode: "candidate_discovered",
      candidateAvailable: true,
      activationEligible: false,
      blockedReason: "validated_package_required",
    });
  });

  it("persists automatic-update policy through the bounded admin endpoint", async () => {
    const policy = {
      schema_version: 1,
      automatic_updates_enabled: true,
      schedule_local_time: "02:00",
      updated_at: "2026-08-18T07:10:00Z",
      updated_by: "admin",
      error_code: null,
    };
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(JSON.stringify(policy), { status: 200 }));
    const client = new VersionManagementClient("http://127.0.0.1:8082", fetchImpl);

    const result = await client.setAutomaticUpdates(true);

    expect(result.automaticUpdatesEnabled).toBe(true);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:8082/api/v1/system/version/update/policy");
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toEqual({ automatic_updates_enabled: true });
  });

  it("queues manual update discovery independently of automatic policy", async () => {
    const queued = {
      schema_version: 1,
      id: "check-1",
      actor_subject: "admin",
      source: "manual",
      status: "queued",
      requested_at: "2026-08-18T07:11:00Z",
      reason: "operator requested",
    };
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(JSON.stringify(queued), { status: 202 }));
    const client = new VersionManagementClient("http://127.0.0.1:8082", fetchImpl);

    const result = await client.requestUpdateCheck(" operator requested ");

    expect(result).toMatchObject({ id: "check-1", status: "queued", reason: "operator requested" });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:8082/api/v1/system/version/update/checks");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ reason: "operator requested" });
  });

  it("rejects drift from the fixed 02:00 server schedule contract", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          ...snapshot,
          update_policy: { ...snapshot.update_policy, schedule_local_time: "03:00" },
        }),
        { status: 200 },
      ),
    );
    const client = new VersionManagementClient("http://127.0.0.1:8082", fetchImpl);

    await expect(client.read()).rejects.toMatchObject({
      status: 502,
      code: "invalid_version_response",
    });
  });

  it("sends only the bounded action contract", async () => {
    const operation = {
      id: "operation-1",
      actor_subject: "admin",
      action: "rollback",
      source_release: "2.0.0",
      target_release: "1.0.0",
      target_bundle_id: "release-1",
      target_commit: "1".repeat(40),
      status: "queued",
      started_at: "2026-08-13T11:00:00Z",
      ended_at: null,
      backup_evidence_id: null,
      result_code: null,
    };
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(JSON.stringify(operation), { status: 202 }));
    const client = new VersionManagementClient("http://127.0.0.1:8082", fetchImpl);

    await client.requestAction({
      action: "rollback",
      targetBundleId: "release-1",
      confirmation: "ROLLBACK release-1",
      reason: "operator approved",
    });

    const [, init] = fetchImpl.mock.calls[0];
    expect(JSON.parse(String(init?.body))).toEqual({
      action: "rollback",
      target_bundle_id: "release-1",
      confirmation: "ROLLBACK release-1",
      reason: "operator approved",
    });
  });

  it("preserves backend hard-stop codes", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ detail: { code: "schema_compatibility_unknown", message: "stop" } }), {
        status: 409,
      }),
    );
    const client = new VersionManagementClient("http://127.0.0.1:8082", fetchImpl);

    await expect(
      client.requestAction({
        action: "update",
        targetBundleId: "release-3",
        confirmation: "APPLY release-3",
      }),
    ).rejects.toMatchObject({ status: 409, code: "schema_compatibility_unknown" });
  });
});
