import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import {
  parseReleaseDirectory,
  readDashboardRuntimeIdentity,
} from "@/lib/runtime-identity";

describe("runtime identity", () => {
  it("parses the deployed frontend release directory", () => {
    expect(
      parseReleaseDirectory(
        "/srv/nexolab/runtime/frontend-releases/2296e3070cbebff687418cf1ac161984086bebdb-20260918T184540Z",
      ),
    ).toEqual({
      sourceCommit: "2296e3070cbebff687418cf1ac161984086bebdb",
      deployedAt: "2026-09-18T18:45:40Z",
    });
  });

  it("returns null commit for a non-release directory", () => {
    expect(parseReleaseDirectory("/srv/nexolab/nexolab-platform")).toEqual({
      sourceCommit: null,
      deployedAt: null,
    });
  });

  it("reads only safe runtime identity fields", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "nexolab-runtime-identity-"));
    const release = path.join(
      root,
      "cfc6f99158276e7e307827414c364cccad176653-20260920T101500Z",
    );
    try {
      await mkdir(path.join(release, ".next"), { recursive: true });
      await writeFile(path.join(release, ".next", "BUILD_ID"), "build-abc123\n", "utf8");

      await expect(readDashboardRuntimeIdentity(release)).resolves.toEqual({
        schema_version: "nexolab-runtime-identity-v1",
        service: "dashboard",
        source_commit: "cfc6f99158276e7e307827414c364cccad176653",
        build_id: "build-abc123",
        deployed_at: "2026-09-20T10:15:00Z",
        identity_source: "release_directory",
      });
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});
