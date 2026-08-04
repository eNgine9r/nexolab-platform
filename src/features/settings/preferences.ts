export const SETTINGS_PREFERENCES_SCHEMA_VERSION = 1 as const;
export const SETTINGS_PREFERENCES_STORAGE_KEY = "nexolab.settings.preferences.v1";

export type SettingsTimeDisplay = "local" | "utc";
export type SettingsTableDensity = "comfortable" | "compact";
export type SettingsMotionPreference = "system" | "reduced";
export type SettingsTelemetryWindow = "1h" | "6h" | "24h";

export type SettingsPreferences = {
  schemaVersion: typeof SETTINGS_PREFERENCES_SCHEMA_VERSION;
  timeDisplay: SettingsTimeDisplay;
  tableDensity: SettingsTableDensity;
  motion: SettingsMotionPreference;
  telemetryWindow: SettingsTelemetryWindow;
};

export type ParsedSettingsPreferences = {
  preferences: SettingsPreferences;
  recovered: boolean;
  reason: string | null;
};

export const DEFAULT_SETTINGS_PREFERENCES: Readonly<SettingsPreferences> = Object.freeze({
  schemaVersion: SETTINGS_PREFERENCES_SCHEMA_VERSION,
  timeDisplay: "local",
  tableDensity: "comfortable",
  motion: "system",
  telemetryWindow: "6h",
});

export function createDefaultSettingsPreferences(): SettingsPreferences {
  return { ...DEFAULT_SETTINGS_PREFERENCES };
}

export function parseSettingsPreferences(raw: string | null): ParsedSettingsPreferences {
  if (raw === null) {
    return {
      preferences: createDefaultSettingsPreferences(),
      recovered: false,
      reason: null,
    };
  }

  let payload: unknown;
  try {
    payload = JSON.parse(raw) as unknown;
  } catch {
    return recoveredDefaults("Локальне значення не є коректним JSON.");
  }

  if (!isRecord(payload)) {
    return recoveredDefaults("Локальне значення не є settings object.");
  }

  if (payload.schemaVersion !== SETTINGS_PREFERENCES_SCHEMA_VERSION) {
    return recoveredDefaults("Версія локальних налаштувань не підтримується.");
  }

  if (!isTimeDisplay(payload.timeDisplay)) {
    return recoveredDefaults("Некоректний формат часових позначок.");
  }
  if (!isTableDensity(payload.tableDensity)) {
    return recoveredDefaults("Некоректна щільність таблиць.");
  }
  if (!isMotionPreference(payload.motion)) {
    return recoveredDefaults("Некоректний режим анімації.");
  }
  if (!isTelemetryWindow(payload.telemetryWindow)) {
    return recoveredDefaults("Некоректне стандартне вікно телеметрії.");
  }

  return {
    preferences: {
      schemaVersion: SETTINGS_PREFERENCES_SCHEMA_VERSION,
      timeDisplay: payload.timeDisplay,
      tableDensity: payload.tableDensity,
      motion: payload.motion,
      telemetryWindow: payload.telemetryWindow,
    },
    recovered: false,
    reason: null,
  };
}

export function serializeSettingsPreferences(preferences: SettingsPreferences): string {
  return JSON.stringify({
    schemaVersion: SETTINGS_PREFERENCES_SCHEMA_VERSION,
    timeDisplay: preferences.timeDisplay,
    tableDensity: preferences.tableDensity,
    motion: preferences.motion,
    telemetryWindow: preferences.telemetryWindow,
  });
}

export function withSettingsPreference<K extends keyof Omit<SettingsPreferences, "schemaVersion">>(
  current: SettingsPreferences,
  key: K,
  value: SettingsPreferences[K],
): SettingsPreferences {
  return {
    ...current,
    schemaVersion: SETTINGS_PREFERENCES_SCHEMA_VERSION,
    [key]: value,
  };
}

function recoveredDefaults(reason: string): ParsedSettingsPreferences {
  return {
    preferences: createDefaultSettingsPreferences(),
    recovered: true,
    reason,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isTimeDisplay(value: unknown): value is SettingsTimeDisplay {
  return value === "local" || value === "utc";
}

function isTableDensity(value: unknown): value is SettingsTableDensity {
  return value === "comfortable" || value === "compact";
}

function isMotionPreference(value: unknown): value is SettingsMotionPreference {
  return value === "system" || value === "reduced";
}

function isTelemetryWindow(value: unknown): value is SettingsTelemetryWindow {
  return value === "1h" || value === "6h" || value === "24h";
}
