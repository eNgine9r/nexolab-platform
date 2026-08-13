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
  offline: true,
  catalog_limit: 20,
};

describe("VersionManagementClient", () => {
  it("parses the offline current-version and catalog read model", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(JSON.stringify(snapshot), { status: 200 }));
    const client = new VersionManagementClient("http://127.0.0.1:8082", fetchImpl);

    const result = await client.read();

    expect(result.offline).toBe(true);
    expect(result.current).toMatchObject({ release: "2.0.0", previousBundleId: "release-1" });
    expect(result.catalog[0]).toMatchObject({ bundleId: "release-2", schemaHead: "schema-2" });
    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:8082/api/v1/system/version",
      expect.objectContaining({ method: "GET", cache: "no-store" }),
    );
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
