import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { readDashboardRuntimeIdentity } from "@/lib/runtime-identity";

const SOURCE = "2296e3070cbebff687418cf1ac161984086bebdb";

async function runtimeFixture(source = SOURCE) {
  const root = await mkdtemp(path.join(os.tmpdir(), "nexolab-runtime-identity-"));
  const release = path.join(root, source + "-20260918T184540Z");
  await mkdir(path.join(release, ".next"), { recursive: true });
  await writeFile(path.join(release, ".next", "BUILD_ID"), "build-abc123\n", "utf8");
  return { root, release };
}

describe("runtime identity", () => {
  it("uses an activation manifest as the authoritative deployment timestamp", async () => {
    const { root, release } = await runtimeFixture();
    const identity = path.join(root, "dashboard-runtime-identity.json");
    try {
      await writeFile(
        identity,
        JSON.stringify({
          schema_version: "nexolab-runtime-identity-v1",
          service: "dashboard",
          source_commit: SOURCE,
          build_id: "build-abc123",
          deployed_at: "2026-09-20T18:30:00+03:00",
          identity_source: "raspberry_activation",
        }) + "\n",
        "utf8",
      );

      await expect(readDashboardRuntimeIdentity({ cwd: release, identityFile: identity })).resolves.toEqual({
        schema_version: "nexolab-runtime-identity-v1",
        service: "dashboard",
        source_commit: SOURCE,
        build_id: "build-abc123",
        deployed_at: "2026-09-20T18:30:00+03:00",
        identity_source: "raspberry_activation",
      });
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
  it("rejects stale activation metadata that does not match the running release", async () => {
    const { root, release } = await runtimeFixture();
    const identity = path.join(root, "dashboard-runtime-identity.json");
    try {
      await writeFile(
        identity,
        JSON.stringify({
          schema_version: "nexolab-runtime-identity-v1",
          service: "dashboard",
          source_commit: "cfc6f99158276e7e307827414c364cccad176653",
          build_id: "build-abc123",
          deployed_at: "2026-09-20T18:30:00+03:00",
          identity_source: "raspberry_activation",
        }) + "\n",
        "utf8",
      );

      await expect(readDashboardRuntimeIdentity({ cwd: release, identityFile: identity })).resolves.toEqual({
        schema_version: "nexolab-runtime-identity-v1",
        service: "dashboard",
        source_commit: SOURCE,
        build_id: "build-abc123",
        deployed_at: null,
        identity_source: "release_directory",
      });
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
  it("reads exact source identity from an offline image manifest", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "nexolab-runtime-container-"));
    const identity = path.join(root, ".nexolab-runtime-identity.json");
    try {
      await mkdir(path.join(root, ".next"), { recursive: true });
      await writeFile(path.join(root, ".next", "BUILD_ID"), "container-build\n", "utf8");
      await writeFile(
        identity,
        JSON.stringify({
          schema_version: "nexolab-runtime-identity-v1",
          service: "dashboard",
          source_commit: SOURCE,
          build_id: "container-build",
          deployed_at: null,
          identity_source: "offline_image_manifest",
        }) + "\n",
        "utf8",
      );

      await expect(readDashboardRuntimeIdentity({ cwd: root, identityFile: identity })).resolves.toEqual({
        schema_version: "nexolab-runtime-identity-v1",
        service: "dashboard",
        source_commit: SOURCE,
        build_id: "container-build",
        deployed_at: null,
        identity_source: "offline_image_manifest",
      });
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});
