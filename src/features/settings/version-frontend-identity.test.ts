import { describe, expect, it, vi } from "vitest";

import { readVersionFrontendIdentity } from "./version-frontend-identity";

describe("version frontend identity", () => {
  const identity = {
    schema_version: "nexolab-runtime-identity-v1",
    service: "dashboard",
    source_commit: "a".repeat(40),
    build_id: "actual-build",
  };
  it("reads only the same-origin frontend identity with caching disabled", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(identity)));
    expect(await readVersionFrontendIdentity(fetchImpl)).toEqual({
      sourceCommit: identity.source_commit,
      buildId: "actual-build",
    });
    expect(fetchImpl).toHaveBeenCalledWith(
      "/api/runtime-identity",
      expect.objectContaining({ cache: "no-store" }),
    );
  });
  it.each([
    null,
    {},
    { ...identity, source_commit: "main" },
    { ...identity, build_id: "" },
    { ...identity, service: "api" },
  ])("does not invent a version from invalid identity %j", async (value) => {
    expect(
      await readVersionFrontendIdentity(
        vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(value))),
      ),
    ).toBeNull();
  });
  it("reports unavailable identity for auth, network and invalid JSON failures", async () => {
    for (const response of [new Response("", { status: 401 }), new Response("google html")]) {
      expect(await readVersionFrontendIdentity(vi.fn<typeof fetch>().mockResolvedValue(response))).toBeNull();
    }
    expect(
      await readVersionFrontendIdentity(vi.fn<typeof fetch>().mockRejectedValue(new TypeError("offline"))),
    ).toBeNull();
  });
});
