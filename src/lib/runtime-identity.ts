import { readFile } from "node:fs/promises";
import path from "node:path";

export const RUNTIME_IDENTITY_SCHEMA = "nexolab-runtime-identity-v1" as const;

const RELEASE_DIRECTORY = /^([0-9a-f]{40})-(\d{8}T\d{6}Z)$/;

export type DashboardRuntimeIdentity = {
  schema_version: typeof RUNTIME_IDENTITY_SCHEMA;
  service: "dashboard";
  source_commit: string | null;
  build_id: string | null;
  deployed_at: string | null;
  identity_source: "release_directory" | "unknown";
};

export function parseReleaseDirectory(cwd: string): {
  sourceCommit: string | null;
  deployedAt: string | null;
} {
  const match = RELEASE_DIRECTORY.exec(path.basename(path.resolve(cwd)));
  if (!match) return { sourceCommit: null, deployedAt: null };

  const stamp = match[2];
  const deployedAt =
    stamp.length === 16
      ? `${stamp.slice(0, 4)}-${stamp.slice(4, 6)}-${stamp.slice(6, 8)}T${stamp.slice(9, 11)}:${stamp.slice(11, 13)}:${stamp.slice(13, 15)}Z`
      : null;

  return { sourceCommit: match[1], deployedAt };
}

export async function readDashboardRuntimeIdentity(
  cwd = process.cwd(),
): Promise<DashboardRuntimeIdentity> {
  const release = parseReleaseDirectory(cwd);

  let buildId: string | null = null;
  try {
    const value = (await readFile(path.join(cwd, ".next", "BUILD_ID"), "utf8")).trim();
    buildId = value || null;
  } catch {
    buildId = null;
  }

  return {
    schema_version: RUNTIME_IDENTITY_SCHEMA,
    service: "dashboard",
    source_commit: release.sourceCommit,
    build_id: buildId,
    deployed_at: release.deployedAt,
    identity_source: release.sourceCommit ? "release_directory" : "unknown",
  };
}
