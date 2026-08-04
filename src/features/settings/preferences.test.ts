import { describe, expect, it } from "vitest";

import {
  createDefaultSettingsPreferences,
  parseSettingsPreferences,
  serializeSettingsPreferences,
  withSettingsPreference,
} from "./preferences";

describe("settings preferences", () => {
  it("uses deterministic defaults when no local value exists", () => {
    expect(parseSettingsPreferences(null)).toEqual({
      preferences: {
        schemaVersion: 1,
        timeDisplay: "local",
        tableDensity: "comfortable",
        motion: "system",
        telemetryWindow: "6h",
      },
      recovered: false,
      reason: null,
    });
  });

  it("recovers from malformed JSON", () => {
    const parsed = parseSettingsPreferences("{not-json");

    expect(parsed.preferences).toEqual(createDefaultSettingsPreferences());
    expect(parsed.recovered).toBe(true);
    expect(parsed.reason).toContain("JSON");
  });

  it("recovers from obsolete schema versions and invalid enum values", () => {
    expect(
      parseSettingsPreferences(
        JSON.stringify({
          schemaVersion: 0,
          timeDisplay: "utc",
          tableDensity: "compact",
          motion: "reduced",
          telemetryWindow: "24h",
        }),
      ).recovered,
    ).toBe(true);

    expect(
      parseSettingsPreferences(
        JSON.stringify({
          schemaVersion: 1,
          timeDisplay: "server",
          tableDensity: "compact",
          motion: "reduced",
          telemetryWindow: "24h",
        }),
      ).recovered,
    ).toBe(true);
  });

  it("round-trips a valid versioned preference object", () => {
    const preferences = {
      schemaVersion: 1 as const,
      timeDisplay: "utc" as const,
      tableDensity: "compact" as const,
      motion: "reduced" as const,
      telemetryWindow: "24h" as const,
    };

    expect(parseSettingsPreferences(serializeSettingsPreferences(preferences))).toEqual({
      preferences,
      recovered: false,
      reason: null,
    });
  });

  it("updates one approved local preference without changing the schema", () => {
    const updated = withSettingsPreference(
      createDefaultSettingsPreferences(),
      "telemetryWindow",
      "1h",
    );

    expect(updated).toEqual({
      schemaVersion: 1,
      timeDisplay: "local",
      tableDensity: "comfortable",
      motion: "system",
      telemetryWindow: "1h",
    });
  });
});
