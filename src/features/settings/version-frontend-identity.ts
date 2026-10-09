export type VersionFrontendIdentity = {
  sourceCommit: string;
  buildId: string;
};

/** This is the frontend serving this browser, independently of package authority. */
export async function readVersionFrontendIdentity(
  fetchImpl: typeof fetch = fetch,
): Promise<VersionFrontendIdentity | null> {
  try {
    const response = await fetchImpl("/api/runtime-identity", {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
      headers: { Accept: "application/json" },
    });
    if (!response.ok) return null;
    const value: unknown = await response.json();
    if (!value || typeof value !== "object") return null;
    const row = value as Record<string, unknown>;
    if (
      row.schema_version !== "nexolab-runtime-identity-v1" ||
      row.service !== "dashboard" ||
      typeof row.source_commit !== "string" ||
      !/^[0-9a-f]{40}$/.test(row.source_commit) ||
      typeof row.build_id !== "string" ||
      !row.build_id.trim()
    ) {
      return null;
    }
    return { sourceCommit: row.source_commit, buildId: row.build_id };
  } catch {
    return null;
  }
}
