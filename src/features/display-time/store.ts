import { parseSettingsPreferences, SETTINGS_PREFERENCES_STORAGE_KEY } from "@/features/settings/preferences";

export const SETTINGS_PREFERENCES_CHANGED_EVENT = "nexolab:settings-preferences-changed";

export function getDisplayTimeZone(): string {
  if (typeof window === "undefined") return "UTC";
  try {
    const preferences = parseSettingsPreferences(
      window.localStorage.getItem(SETTINGS_PREFERENCES_STORAGE_KEY),
    );
    if (preferences.preferences.timeDisplay === "utc") return "UTC";
  } catch {
    // Optional browser storage must not prevent local presentation.
  }
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

export function subscribeDisplayTimeZone(callback: () => void): () => void {
  const storage = (event: StorageEvent) => {
    if (event.key === null || event.key === SETTINGS_PREFERENCES_STORAGE_KEY) callback();
  };
  window.addEventListener("storage", storage);
  window.addEventListener(SETTINGS_PREFERENCES_CHANGED_EVENT, callback);
  window.addEventListener("pageshow", callback);
  window.addEventListener("focus", callback);
  return () => {
    window.removeEventListener("storage", storage);
    window.removeEventListener(SETTINGS_PREFERENCES_CHANGED_EVENT, callback);
    window.removeEventListener("pageshow", callback);
    window.removeEventListener("focus", callback);
  };
}

export function notifySettingsPreferencesChanged(): void {
  window.dispatchEvent(new Event(SETTINGS_PREFERENCES_CHANGED_EVENT));
}
