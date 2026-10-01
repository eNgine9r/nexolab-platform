import { LIVE_SELECTION_LIMIT } from "./live-telemetry";

export type SelectionPreferenceStorage = Pick<Storage, "getItem" | "setItem">;

function browserStorage(): SelectionPreferenceStorage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

function storageKey(organizationId: string): string | null {
  const organization = organizationId.trim();
  return organization ? `nexolab.live-comparison.v1:${encodeURIComponent(organization)}` : null;
}

function validKey(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 2048;
}

export function readLiveSelectionPreference(
  organizationId: string,
  storage: SelectionPreferenceStorage | null = browserStorage(),
): string[] {
  const key = storageKey(organizationId);
  if (!key || !storage) return [];
  try {
    const raw = storage.getItem(key);
    if (!raw || raw.length > 20_000) return [];
    const value = JSON.parse(raw) as { version?: unknown; keys?: unknown } | null;
    if (!value || value.version !== 1 || !Array.isArray(value.keys)) return [];
    if (value.keys.length > LIVE_SELECTION_LIMIT || !value.keys.every(validKey)) return [];
    if (new Set(value.keys).size !== value.keys.length) return [];
    return value.keys;
  } catch {
    return [];
  }
}

export function writeLiveSelectionPreference(
  organizationId: string,
  keys: readonly string[],
  storage: SelectionPreferenceStorage | null = browserStorage(),
): boolean {
  const key = storageKey(organizationId);
  if (!key || !storage) return false;
  try {
    const selected = [...new Set(keys.filter(validKey))].slice(0, LIVE_SELECTION_LIMIT);
    const value = JSON.stringify({ version: 1, keys: selected });
    if (storage.getItem(key) !== value) storage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}
