import { describe, expect, it } from "vitest";

import type { DashboardKpiValue } from "@/lib/telemetry/dashboard-state";

import { activeSessionsKpi } from "./sessions-panel";

const BASE: DashboardKpiValue = {
  label: "Активних сесій",
  value: "—",
  detail: "",
  trend: "",
  tone: "cyan",
  icon: "session",
  badge: "LIVE",
  badgeTone: "live",
};

describe("#1845 Overview active sessions KPI", () => {
  it("counts the running session (was a dash with 'Session API not connected')", () => {
    const kpi = activeSessionsKpi(BASE, { running: 1, paused: 0, ready: 0 }, false);
    expect(kpi).toMatchObject({ value: "1", detail: "Виконується: 1 · призупинено: 0", badgeTone: "live" });
  });

  it("counts paused sessions as active and names ready ones separately", () => {
    const kpi = activeSessionsKpi(BASE, { running: 0, paused: 1, ready: 2 }, false);
    expect(kpi.value).toBe("1");
    expect(kpi.trend).toBe("готові до запуску: 2");
  });

  it("states a failed refresh before anything else, with its own badge (review)", () => {
    const kpi = activeSessionsKpi(BASE, { running: 1, paused: 0, ready: 2 }, true);
    expect(kpi.trend).toBe("оновлення не вдалося; останній відомий стан");
    expect(kpi).toMatchObject({ badge: "stale", badgeTone: "stale" });
  });

  it("says zero only when the totals are known, and never guesses when they are not", () => {
    expect(activeSessionsKpi(BASE, { running: 0, paused: 0, ready: 0 }, false).value).toBe("0");
    expect(activeSessionsKpi(BASE, null, false)).toMatchObject({ value: "—", detail: "Завантаження сесій…" });
    expect(activeSessionsKpi(BASE, null, true)).toMatchObject({
      value: "—",
      detail: "Список сесій недоступний",
      badgeTone: "error",
    });
  });
});
