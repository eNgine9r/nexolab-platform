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
  it("counts the running session the panel lists (was a dash with 'Session API not connected')", () => {
    const kpi = activeSessionsKpi(BASE, [{ state: "running" }, { state: "completed" }], false);
    expect(kpi.value).toBe("1");
    expect(kpi.detail).toBe("Виконується: 1 · призупинено: 0");
  });

  it("counts paused sessions as active and names ready ones separately", () => {
    const kpi = activeSessionsKpi(BASE, [{ state: "paused" }, { state: "ready" }, { state: "ready" }], false);
    expect(kpi.value).toBe("1");
    expect(kpi.trend).toBe("готові до запуску: 2");
  });

  it("says zero only when the list is known, and never guesses when it is not", () => {
    expect(activeSessionsKpi(BASE, [], false).value).toBe("0");
    expect(activeSessionsKpi(BASE, null, false)).toMatchObject({ value: "—", detail: "Завантаження сесій…" });
    expect(activeSessionsKpi(BASE, null, true)).toMatchObject({
      value: "—",
      detail: "Список сесій недоступний",
    });
  });
});
