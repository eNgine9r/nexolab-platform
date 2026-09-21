import { readFile } from "node:fs/promises";
import path from "node:path";

export const RUNTIME_IDENTITY_SCHEMA = "nexolab-runtime-identity-v1" as const;

const SOURCE_COMMIT = /^[0-9a-f]{40}$/;

export type DashboardRuntimeIdentity = {
  schema_version: typeof RUNTIME_IDENTITY_SCHEMA;
  service: "dashboard";
  source_commit: string | null;
  build_id: string | null;
  deployed_at: string | null;
  identity_source:
    | "raspberry_activation"
    | "raspberry_rollback"
    | "offline_image_manifest"
    | "release_directory"
    | "unknown";
};

type RuntimeIdentityOptions = {
  cwd?: string;
  identityFile?: string | null;
};
function releaseSourceCommit(cwd: string): string | null {
  const name = path.basename(path.resolve(cwd));
  const source = name.split("-", 1)[0] ?? "";
  return SOURCE_COMMIT.test(source) ? source : null;
}

async function readBuildId(cwd: string): Promise<string | null> {
  try {
    const value = (await readFile(path.join(cwd, ".next", "BUILD_ID"), "utf8")).trim();
    return value || null;
  } catch {
    return null;
  }
}

async function readIdentityManifest(file: string): Promise<DashboardRuntimeIdentity | null> {
  try {
    const raw = JSON.parse(await readFile(file, "utf8")) as Partial<DashboardRuntimeIdentity>;
    if (
      raw.schema_version !== RUNTIME_IDENTITY_SCHEMA ||
      raw.service !== "dashboard" ||
      typeof raw.source_commit !== "string" ||
      !SOURCE_COMMIT.test(raw.source_commit)
    ) {
      return null;
    }
    if (raw.build_id !== null && typeof raw.build_id !== "string") return null;
    if (raw.deployed_at !== null && typeof raw.deployed_at !== "string") return null;
    if (
      !["raspberry_activation", "raspberry_rollback", "offline_image_manifest"].includes(
        String(raw.identity_source),
      )
    ) {
      return null;
    }
    return {
      schema_version: RUNTIME_IDENTITY_SCHEMA,
      service: "dashboard",
      source_commit: raw.source_commit,
      build_id: raw.build_id ?? null,
      deployed_at: raw.deployed_at ?? null,
      identity_source: raw.identity_source as DashboardRuntimeIdentity["identity_source"],
    };
  } catch {
    return null;
  }
}

export async function readDashboardRuntimeIdentity(
  options: RuntimeIdentityOptions = {},
): Promise<DashboardRuntimeIdentity> {
  const cwd = options.cwd ?? process.cwd();
  const buildId = await readBuildId(cwd);
  const releaseSource = releaseSourceCommit(cwd);
  const identityFile =
    options.identityFile ??
    process.env.NEXOLAB_RUNTIME_IDENTITY_FILE ??
    path.join(cwd, ".nexolab-runtime-identity.json");
  const manifest = await readIdentityManifest(identityFile);
  const sourceMatchesRelease = !releaseSource || manifest?.source_commit === releaseSource;
  const buildMatchesRuntime =
    typeof manifest?.build_id === "string" &&
    manifest.build_id.length > 0 &&
    typeof buildId === "string" &&
    buildId.length > 0 &&
    manifest.build_id === buildId;

  if (manifest && sourceMatchesRelease && buildMatchesRuntime) {
    return {
      ...manifest,
      build_id: buildId ?? manifest.build_id,
    };
  }

  return {
    schema_version: RUNTIME_IDENTITY_SCHEMA,
    service: "dashboard",
    source_commit: releaseSource,
    build_id: buildId,
    deployed_at: null,
    identity_source: releaseSource ? "release_directory" : "unknown",
  };
}
