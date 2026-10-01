"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  notifySettingsPreferencesChanged,
  SETTINGS_PREFERENCES_CHANGED_EVENT,
} from "@/features/display-time/store";

import {
  createDefaultSettingsPreferences,
  parseSettingsPreferences,
  serializeSettingsPreferences,
  SETTINGS_PREFERENCES_STORAGE_KEY,
  type SettingsPreferences,
  withSettingsPreference,
} from "@/features/settings/preferences";

type EditableSettingsPreference = keyof Omit<SettingsPreferences, "schemaVersion">;

export type SettingsPreferencesModel = {
  preferences: SettingsPreferences;
  loaded: boolean;
  recovered: boolean;
  recoveryReason: string | null;
  updatePreference: (
    key: EditableSettingsPreference,
    value: SettingsPreferences[EditableSettingsPreference],
  ) => void;
  reset: () => void;
};

function persist(preferences: SettingsPreferences): boolean {
  try {
    window.localStorage.setItem(SETTINGS_PREFERENCES_STORAGE_KEY, serializeSettingsPreferences(preferences));
    return true;
  } catch {
    return false;
  }
}

export function useSettingsPreferences(): SettingsPreferencesModel {
  const [preferences, setPreferences] = useState<SettingsPreferences>(createDefaultSettingsPreferences);
  const [loaded, setLoaded] = useState(false);
  const [recovered, setRecovered] = useState(false);
  const [recoveryReason, setRecoveryReason] = useState<string | null>(null);

  useEffect(() => {
    const load = () => {
      let raw: string | null = null;
      try {
        raw = window.localStorage.getItem(SETTINGS_PREFERENCES_STORAGE_KEY);
      } catch {
        setPreferences(createDefaultSettingsPreferences());
        setRecovered(true);
        setRecoveryReason("Browser storage недоступний; використано безпечні локальні defaults.");
        setLoaded(true);
        return;
      }

      const parsed = parseSettingsPreferences(raw);
      setPreferences(parsed.preferences);
      setRecovered(parsed.recovered);
      setRecoveryReason(parsed.reason);
      if (parsed.recovered) persist(parsed.preferences);
      setLoaded(true);
    };
    const timeoutId = window.setTimeout(load, 0);
    const storage = (event: StorageEvent) => {
      if (event.key === null || event.key === SETTINGS_PREFERENCES_STORAGE_KEY) load();
    };
    window.addEventListener("storage", storage);
    window.addEventListener(SETTINGS_PREFERENCES_CHANGED_EVENT, load);

    return () => {
      window.clearTimeout(timeoutId);
      window.removeEventListener("storage", storage);
      window.removeEventListener(SETTINGS_PREFERENCES_CHANGED_EVENT, load);
    };
  }, []);

  const updatePreference = useCallback(
    (key: EditableSettingsPreference, value: SettingsPreferences[EditableSettingsPreference]) => {
      let current = preferences;
      try {
        current = parseSettingsPreferences(
          window.localStorage.getItem(SETTINGS_PREFERENCES_STORAGE_KEY),
        ).preferences;
      } catch {
        setRecovered(true);
        setRecoveryReason(
          "Не вдалося зберегти налаштування: сховище браузера недоступне. Повторіть дію після відновлення доступу.",
        );
        return;
      }
      const next = withSettingsPreference(current, key, value);
      if (!persist(next)) {
        setRecovered(true);
        setRecoveryReason(
          "Не вдалося зберегти налаштування браузера. Попередні значення залишено; перевірте доступ до сховища та повторіть дію.",
        );
        return;
      }
      setPreferences(next);
      setRecovered(false);
      setRecoveryReason(null);
      notifySettingsPreferencesChanged();
    },
    [preferences],
  );

  const reset = useCallback(() => {
    const defaults = createDefaultSettingsPreferences();
    if (!persist(defaults)) {
      setRecovered(true);
      setRecoveryReason(
        "Не вдалося зберегти скидання налаштувань браузера. Попередні значення залишено; повторіть дію.",
      );
      return;
    }
    setPreferences(defaults);
    setRecovered(false);
    setRecoveryReason(null);
    notifySettingsPreferencesChanged();
  }, []);

  return useMemo(
    () => ({
      preferences,
      loaded,
      recovered,
      recoveryReason,
      updatePreference,
      reset,
    }),
    [loaded, preferences, recovered, recoveryReason, reset, updatePreference],
  );
}
