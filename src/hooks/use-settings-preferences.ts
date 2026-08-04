"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

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

function persist(preferences: SettingsPreferences): void {
  try {
    window.localStorage.setItem(
      SETTINGS_PREFERENCES_STORAGE_KEY,
      serializeSettingsPreferences(preferences),
    );
  } catch {
    // Local preferences are optional and never affect laboratory runtime behavior.
  }
}

export function useSettingsPreferences(): SettingsPreferencesModel {
  const [preferences, setPreferences] = useState<SettingsPreferences>(
    createDefaultSettingsPreferences,
  );
  const [loaded, setLoaded] = useState(false);
  const [recovered, setRecovered] = useState(false);
  const [recoveryReason, setRecoveryReason] = useState<string | null>(null);

  useEffect(() => {
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
  }, []);

  const updatePreference = useCallback(
    (
      key: EditableSettingsPreference,
      value: SettingsPreferences[EditableSettingsPreference],
    ) => {
      setPreferences((current) => {
        const next = withSettingsPreference(current, key, value);
        persist(next);
        return next;
      });
      setRecovered(false);
      setRecoveryReason(null);
    },
    [],
  );

  const reset = useCallback(() => {
    const defaults = createDefaultSettingsPreferences();
    persist(defaults);
    setPreferences(defaults);
    setRecovered(false);
    setRecoveryReason(null);
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
