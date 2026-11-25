import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DashboardIntervalStatistics } from "@/components/live-dashboards/dashboard-interval-statistics";
import {
  appendIntervalSample,
  computeIntervalStatistics,
  createIntervalSampleColumns,
} from "@/features/charts/interval-statistics";
import { chartSeriesKey } from "@/features/charts";
import {
  buildSavedDashboardChartGroups,
  savedDashboardChartIdentity,
} from "@/features/live-dashboards/chart";
import { dashboardItemIdentity } from "@/features/live-dashboards/model";
import { buildDashboardStatisticsRows } from "@/features/live-dashboards/statistics-rows";
import type { LiveDashboardItem, LiveDashboardSeries } from "@/features/live-dashboards/types";

const START = Date.parse("2026-11-22T00:00:00Z");
const DOMAIN = { fromMs: START, toMs: START + 600_000 };

function item(id: string, position: number, channelId: string): LiveDashboardItem {
  return {
    id,
    position,
    channel_ref_id: `ref-${id}`,
    channel_id: channelId,
    metric: "temperature.probe",
    native_unit: "°C",
    visualization: "line",
    color: "#22AAFF",
    display_unit: "°C",
  };
}

const a = item("a", 1, "T-1");
const b = item("b", 2, "T-2");
const series: LiveDashboardSeries[] = [
  { item: a, latest: null, history: [] },
  { item: b, latest: null, history: [] },
];

function provider() {
  const store: Record<string, ReturnType<typeof createIntervalSampleColumns>> = {};
  const full = createIntervalSampleColumns();
  for (let index = 0; index <= 60; index += 1) appendIntervalSample(full, START + index * 10_000, index);
  store[dashboardItemIdentity(a)] = full;
  const sparse = createIntervalSampleColumns();
  for (let index = 0; index < 10; index += 1) appendIntervalSample(sparse, START + index * 10_000, 7);
  store[dashboardItemIdentity(b)] = sparse;
  return (identity: string, fromMs: number, toMs: number) =>
    store[identity] ? computeIntervalStatistics(store[identity], fromMs, toMs) : null;
}

function groups(hidden: ReadonlySet<string> = new Set(), solo: string | null = null) {
  return buildSavedDashboardChartGroups({
    dashboardId: "d",
    series,
    status: "live",
    xDomain: DOMAIN,
    hiddenSeriesKeys: hidden,
    soloSeriesKey: solo,
  });
}

describe("saved dashboard interval statistics rows", () => {
  it("returns raw-sample statistics for each visible series and follows the supplied interval", () => {
    const rows = buildDashboardStatisticsRows("d", series, groups(), DOMAIN, provider());
    expect(rows.map((row) => row.name)).toHaveLength(2);
    expect(rows[0].statistics).toMatchObject({ min: 0, max: 60, average: 30, validCount: 61 });
    const zoomed = buildDashboardStatisticsRows(
      "d",
      series,
      groups(),
      { fromMs: START + 200_000, toMs: START + 300_000 },
      provider(),
    );
    expect(zoomed[0].statistics).toMatchObject({ min: 20, max: 30, validCount: 11 });
  });

  it("omits hidden series and respects solo", () => {
    const keyA = chartSeriesKey(savedDashboardChartIdentity("d", series[0]));
    const keyB = chartSeriesKey(savedDashboardChartIdentity("d", series[1]));
    expect(
      buildDashboardStatisticsRows("d", series, groups(new Set([keyA])), DOMAIN, provider()),
    ).toHaveLength(1);
    const solo = buildDashboardStatisticsRows("d", series, groups(new Set(), keyB), DOMAIN, provider());
    expect(solo).toHaveLength(1);
    expect(solo[0].seriesKey).toBe(keyB);
  });

  it("yields null statistics when no provider exists", () => {
    const rows = buildDashboardStatisticsRows("d", series, groups(), DOMAIN, undefined);
    expect(rows.every((row) => row.statistics === null)).toBe(true);
  });
});

describe("DashboardIntervalStatistics component", () => {
  it("shows exact values, withholds an insufficiently covered average and labels the scope", () => {
    const rows = buildDashboardStatisticsRows("d", series, groups(), DOMAIN, provider());
    render(
      <DashboardIntervalStatistics
        rows={rows}
        fromMs={DOMAIN.fromMs}
        toMs={DOMAIN.toMs}
        isViewport={false}
        displayTimeZone="UTC"
      />,
    );
    expect(screen.getByTestId("dashboard-interval-statistics-scope")).toHaveTextContent(
      "Весь запитаний інтервал",
    );
    const bodyRows = screen.getAllByTestId("dashboard-statistics-row");
    expect(bodyRows).toHaveLength(2);
    expect(within(bodyRows[0]).getByText(/60[.,]00 °C/)).toBeInTheDocument();
    expect(within(bodyRows[0]).getByText(/30[.,]00 °C/)).toBeInTheDocument();
    expect(within(bodyRows[1]).getByText(/недостатнє покриття/)).toBeInTheDocument();
  });

  it("labels a zoomed viewport and renders nothing without rows", () => {
    const { rerender, container } = render(
      <DashboardIntervalStatistics rows={[]} fromMs={0} toMs={1} isViewport={false} displayTimeZone="UTC" />,
    );
    expect(container).toBeEmptyDOMElement();
    const rows = buildDashboardStatisticsRows("d", series, groups(), DOMAIN, provider());
    rerender(
      <DashboardIntervalStatistics
        rows={rows}
        fromMs={DOMAIN.fromMs}
        toMs={DOMAIN.toMs}
        isViewport
        displayTimeZone="UTC"
      />,
    );
    expect(screen.getByTestId("dashboard-interval-statistics-scope")).toHaveTextContent("Видимий");
  });
});
