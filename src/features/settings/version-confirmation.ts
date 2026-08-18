import type { VersionAction } from "./version-management";

export function versionConfirmationPhrase(action: VersionAction, targetBundleId: string): string {
  return action === "update" ? `APPLY ${targetBundleId}` : `ROLLBACK ${targetBundleId}`;
}
