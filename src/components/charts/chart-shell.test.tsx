import { notifySettingsPreferencesChanged } from "@/features/display-time/store";
import {
  createDefaultSettingsPreferences,
  SETTINGS_PREFERENCES_STORAGE_KEY,
} from "@/features/settings/preferences";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { useEffect } from "react";
import { describe, expect, it, vi } from "vitest";

import { chartSeriesKey } from "@/features/charts/domain";
import { createBenchmarkScene } from "@/features/charts/fixtures";
import { formatChartExactTimestamp } from "@/features/charts/format";

import { ChartShell, formatChartWindowDuration } from "./chart-shell";
import { useChartView } from "./chart-view-context";

describe("ChartShell accessibility contract", () => {
  it("reformats the same inspector sample and keeps values, period and series intact", () => {
    localStorage.setItem(
      SETTINGS_PREFERENCES_STORAGE_KEY,
      JSON.stringify({ ...createDefaultSettingsPreferences(), timeDisplay: "utc" }),
    );
    const scene = createBenchmarkScene(1);
    const point = {
      ...scene.series[0].segments[0].points[0],
      timestampMs: Date.parse("2026-07-01T10:20:30Z"),
      value: 25.7,
    };
    render(
      <ChartShell
        title="Timezone test"
        context="fixture"
        selectedRange="15 min"
        series={scene.series}
        inspection={{
          timestampMs: point.timestampMs,
          series: [{ seriesKey: chartSeriesKey(scene.series[0].identity), point, freshness: "live" }],
        }}
        onToggleSeries={vi.fn()}
        onSoloSeries={vi.fn()}
        onResetZoom={vi.fn()}
      >
        <div>plot</div>
      </ChartShell>,
    );
    const inspector = screen.getByTestId("chart-inspector");
    expect(inspector).toHaveTextContent("10:20:30");
    expect(screen.getByTestId("chart-display-timezone")).toHaveTextContent("UTC");
    const actual = new Intl.DateTimeFormat().resolvedOptions();
    vi.spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions").mockReturnValue({
      ...actual,
      timeZone: "Europe/Kyiv",
    });
    localStorage.setItem(
      SETTINGS_PREFERENCES_STORAGE_KEY,
      JSON.stringify(createDefaultSettingsPreferences()),
    );
    act(() => notifySettingsPreferencesChanged());
    expect(screen.getByTestId("chart-inspector")).toBe(inspector);
    expect(inspector).toHaveTextContent("13:20:30");
    expect(inspector).toHaveTextContent("25.70 °C");
    expect(screen.getByTestId("chart-display-timezone")).toHaveTextContent("Europe/Kyiv");
    expect(screen.getByTestId("chart-accessible-summary")).toHaveTextContent(
      "Range 15 min. 1 series visible.",
    );
    vi.restoreAllMocks();
    localStorage.clear();
  });
  it("provides non-color state text and keyboard-operable legend controls", () => {
    const scene = createBenchmarkScene(1);
    const toggle = vi.fn();
    const solo = vi.fn();
    render(
      <ChartShell
        title="Fixture telemetry"
        context="Benchmark"
        selectedRange="15 min"
        series={scene.series}
        inspection={null}
        onToggleSeries={toggle}
        onSoloSeries={solo}
        onResetZoom={vi.fn()}
      >
        <div>plot</div>
      </ChartShell>,
    );

    expect(screen.getByTestId("chart-accessible-summary")).toHaveTextContent(
      "Range 15 min. 1 series visible. Axes 1. Units °C. State Live.",
    );
    expect(screen.getByLabelText("Chart legend")).toHaveTextContent("valid · Live");
    fireEvent.click(screen.getByRole("button", { name: /^Hide / }));
    fireEvent.click(screen.getByRole("button", { name: /^Solo / }));
    expect(toggle).toHaveBeenCalledTimes(1);
    expect(solo).toHaveBeenCalledTimes(1);
  });

  it("names only visible mixed-unit axes in the accessible summary", () => {
    const scene = createBenchmarkScene(3);
    const series = scene.series.map((item, index) => {
      const definitions = [
        { channelId: "voltage", metric: "electrical.voltage", unit: "V" },
        { channelId: "current", metric: "electrical.current", unit: "A" },
        { channelId: "power", metric: "electrical.active_power", unit: "W" },
      ];
      const definition = definitions[index];
      return {
        ...item,
        identity: {
          ...item.identity,
          equipmentId: "meter-01",
          channelId: definition.channelId,
          metric: definition.metric,
          nativeUnit: definition.unit,
        },
        visible: index !== 1,
      };
    });
    const props = {
      title: "Meter telemetry",
      context: "V · A · W",
      selectedRange: "Live",
      inspection: null,
      onToggleSeries: vi.fn(),
      onSoloSeries: vi.fn(),
      onResetZoom: vi.fn(),
    };
    const { rerender } = render(
      <ChartShell {...props} series={series}>
        <div>plot</div>
      </ChartShell>,
    );

    expect(screen.getByTestId("chart-accessible-summary")).toHaveTextContent(
      "2 series visible. Axes 2. Units W, V.",
    );

    rerender(
      <ChartShell {...props} series={series.map((item) => ({ ...item, visible: true }))}>
        <div>plot</div>
      </ChartShell>,
    );
    expect(screen.getByTestId("chart-accessible-summary")).toHaveTextContent(
      "3 series visible. Axes 3. Units W, A, V.",
    );
  });

  it("keeps one fixed-footprint inspector mounted and formats every visible series deterministically", () => {
    const scene = createBenchmarkScene(2);
    const firstSeries = scene.series[0];
    const secondSeries = scene.series[1];
    const firstPoint = { ...firstSeries.segments[0].points[0], value: 25.700000000000003 };
    const secondPoint = secondSeries.segments[0].points[0];
    const props = {
      title: "Fixture telemetry",
      context: "Benchmark",
      selectedRange: "15 min",
      series: scene.series,
      onToggleSeries: vi.fn(),
      onSoloSeries: vi.fn(),
      onResetZoom: vi.fn(),
    };
    const { rerender } = render(
      <ChartShell {...props} inspection={null}>
        <div>plot</div>
      </ChartShell>,
    );

    const inspector = screen.getByTestId("chart-inspector");
    expect(inspector).toHaveClass("min-h-44");
    expect(inspector).toHaveTextContent("Move the shared cursor or use keyboard inspection.");

    rerender(
      <ChartShell
        {...props}
        inspection={{
          timestampMs: firstPoint.timestampMs,
          series: [
            {
              seriesKey: chartSeriesKey(firstSeries.identity),
              point: firstPoint,
              freshness: firstSeries.freshness,
            },
            {
              seriesKey: chartSeriesKey(secondSeries.identity),
              point: secondPoint,
              freshness: secondSeries.freshness,
            },
          ],
        }}
      >
        <div>plot</div>
      </ChartShell>,
    );

    expect(screen.getByTestId("chart-inspector")).toBe(inspector);
    expect(inspector).toHaveTextContent("Nearest measured sample per visible series.");
    expect(inspector).toHaveTextContent(formatChartExactTimestamp(firstPoint.timestampMs));
    expect(inspector).toHaveTextContent("25.70 °C");
    expect(inspector).not.toHaveTextContent("25.700000000000003");
    expect(within(inspector).getAllByRole("row")).toHaveLength(3);
  });

  it("keeps the legend on latest telemetry while the inspector stays on the cursor snapshot", () => {
    const scene = createBenchmarkScene(1);
    const sourceSeries = scene.series[0];
    const lastSegmentIndex = sourceSeries.segments.length - 1;
    const lastSegment = sourceSeries.segments[lastSegmentIndex];
    const latestPoint = { ...lastSegment.points.at(-1)!, value: 9.876 };
    const series = {
      ...sourceSeries,
      segments: sourceSeries.segments.map((segment, segmentIndex) =>
        segmentIndex === lastSegmentIndex
          ? { ...segment, points: [...segment.points.slice(0, -1), latestPoint] }
          : segment,
      ),
    };
    const cursorPoint = { ...sourceSeries.segments[0].points[0], value: 25.7 };

    render(
      <ChartShell
        title="Fixture telemetry"
        context="Benchmark"
        selectedRange="15 min"
        series={[series]}
        inspection={{
          timestampMs: cursorPoint.timestampMs,
          series: [
            {
              seriesKey: chartSeriesKey(series.identity),
              point: cursorPoint,
              freshness: series.freshness,
            },
          ],
        }}
        onToggleSeries={vi.fn()}
        onSoloSeries={vi.fn()}
        onResetZoom={vi.fn()}
      >
        <div>plot</div>
      </ChartShell>,
    );

    expect(screen.getByText("9.88 °C", { exact: true })).toBeVisible();
    expect(screen.getByTestId("chart-inspector")).toHaveTextContent("25.70 °C");
  });

  it("renders a mutually exclusive placeholder when one series has no nearby sample", () => {
    const scene = createBenchmarkScene(1);
    const series = scene.series[0];
    render(
      <ChartShell
        title="Fixture telemetry"
        context="Benchmark"
        selectedRange="15 min"
        series={scene.series}
        inspection={{
          timestampMs: series.segments[0].points[0].timestampMs + 2_500,
          series: [
            {
              seriesKey: chartSeriesKey(series.identity),
              point: null,
              freshness: series.freshness,
            },
          ],
        }}
        onToggleSeries={vi.fn()}
        onSoloSeries={vi.fn()}
        onResetZoom={vi.fn()}
      >
        <div>plot</div>
      </ChartShell>,
    );

    const inspector = screen.getByTestId("chart-inspector");
    const row = within(inspector).getAllByRole("row")[1];
    expect(row).toHaveTextContent("—");
    expect(row).not.toHaveTextContent(`${series.segments[0].points[0].value}`);
  });

  it("supports Ukrainian operator copy without changing the default chart contract", () => {
    const scene = createBenchmarkScene(1);
    render(
      <ChartShell
        title="Історія температур XJP60D · °C"
        context="Температура · Огляд"
        selectedRange="1г"
        series={scene.series}
        inspection={null}
        onToggleSeries={vi.fn()}
        onSoloSeries={vi.fn()}
        onResetZoom={vi.fn()}
        locale="uk"
      >
        <div>plot</div>
      </ChartShell>,
    );

    expect(screen.getByRole("button", { name: "Скинути масштаб" })).toBeVisible();
    expect(screen.getByRole("button", { name: /^Приховати / })).toBeVisible();
    expect(screen.getByRole("button", { name: /^Лише / })).toBeVisible();
    // #1878: icon controls only, no textual card buttons.
    expect(screen.queryByRole("button", { name: "Приховати" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Лише цей" })).toBeNull();
    expect(screen.getByLabelText("Легенда графіка")).toHaveTextContent("Актуально");
    expect(screen.getByTestId("chart-inspector")).toHaveTextContent("Точні значення");
    expect(screen.getByTestId("chart-accessible-summary")).toHaveTextContent("Період 1г");
  });

  it("labels a fixed custom period as such instead of claiming it is live (#1683)", () => {
    const scene = createBenchmarkScene(1);
    render(
      <ChartShell
        title="Історія температур"
        context="Температура · Огляд"
        selectedRange="Власний період"
        series={scene.series.map((series) => ({ ...series, freshness: "historical" as const }))}
        inspection={null}
        onToggleSeries={vi.fn()}
        onSoloSeries={vi.fn()}
        onResetZoom={vi.fn()}
        locale="uk"
      >
        <div>plot</div>
      </ChartShell>,
    );

    expect(screen.getByLabelText("Легенда графіка")).toHaveTextContent("Фіксований період");
    expect(screen.getByLabelText("Легенда графіка")).not.toHaveTextContent("Актуально");
    expect(screen.getByTestId("chart-accessible-summary")).toHaveTextContent("Стан Фіксований період");
  });
});

describe("ChartShell truthful empty and invalid states (chart audit 2026-11-21)", () => {
  it("explains a visible series without valid points instead of drawing silent empty axes", () => {
    const scene = createBenchmarkScene(1);
    const series = [
      {
        ...scene.series[0],
        name: "K106 · 106-01",
        identity: { ...scene.series[0].identity, nativeUnit: "degC" },
        segments: [],
        freshness: "invalid" as const,
        latest: { timestampMs: Date.parse("2026-11-21T20:00:00Z"), value: null, quality: "unknown" as const },
      },
    ];
    render(
      <ChartShell
        locale="uk"
        title="Live дані · K106"
        context="°C"
        selectedRange="24 h"
        series={series}
        inspection={null}
        onToggleSeries={vi.fn()}
        onSoloSeries={vi.fn()}
        onResetZoom={vi.fn()}
      >
        <div>plot</div>
      </ChartShell>,
    );
    const notice = screen.getByTestId("chart-no-valid-points");
    expect(notice).toHaveTextContent("Немає валідних точок");
    expect(notice).toHaveTextContent("K106 · 106-01: невідома якість");
    expect(screen.getAllByText("Немає валідних даних").length).toBeGreaterThan(0); // never "Актуально"
    expect(screen.queryByText("Актуально")).toBeNull();
    expect(screen.getByText("— °C")).toBeInTheDocument(); // display unit, no stale value
    expect(screen.getByRole("button", { name: "Скинути масштаб" })).toBeInTheDocument();
  });

  it("states when stored history starts later than the requested range (#1677)", () => {
    const scene = createBenchmarkScene(1);
    const first = Math.min(
      ...scene.series[0].segments.flatMap((segment) => segment.points.map((point) => point.timestampMs)),
    );
    const day = 24 * 3_600_000;
    const shell = (fromMs: number) => (
      <ChartShell
        title="Історія"
        context="°C"
        selectedRange="7 днів"
        series={scene.series}
        inspection={null}
        onToggleSeries={vi.fn()}
        onSoloSeries={vi.fn()}
        onResetZoom={vi.fn()}
        locale="uk"
        requestedWindow={{ fromMs, toMs: first + 7 * day }}
      >
        <div>plot</div>
      </ChartShell>
    );
    const { rerender } = render(shell(first - 6 * day));
    const notice = screen.getByTestId("chart-partial-history");
    expect(notice).toHaveTextContent("Історія доступна не за весь період");
    expect(notice).toHaveTextContent("немає даних, а не нулі");
    rerender(shell(first));
    expect(screen.queryByTestId("chart-partial-history")).toBeNull();
  });
});

describe("#1843 Y scale and visible interval", () => {
  function Probe({
    visible,
    full,
  }: {
    visible: { fromMs: number; toMs: number };
    full: { fromMs: number; toMs: number };
  }) {
    const { yScale, reportVisibleDomain } = useChartView();
    useEffect(() => reportVisibleDomain(visible, full), [full, reportVisibleDomain, visible]);
    return <output data-testid="probe-y-scale">{JSON.stringify(yScale)}</output>;
  }

  it("defaults to Auto, switches modes, takes manual bounds and names the zoomed interval", () => {
    const scene = createBenchmarkScene(1);
    const full = scene.xDomain;
    const visible = { fromMs: full.fromMs + 60_000, toMs: full.fromMs + 60_000 + 70 * 60_000 };
    render(
      <ChartShell
        title="Температура"
        context="Огляд"
        selectedRange="7 днів"
        series={scene.series}
        inspection={null}
        onToggleSeries={vi.fn()}
        onSoloSeries={vi.fn()}
        onResetZoom={vi.fn()}
        locale="uk"
      >
        <Probe visible={visible} full={full} />
      </ChartShell>,
    );
    const group = screen.getByRole("group", { name: "Шкала Y" });
    expect(within(group).getByRole("button", { name: "Авто" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("probe-y-scale")).toHaveTextContent('"mode":"auto"');
    expect(screen.getByTestId("chart-visible-window")).toHaveTextContent("1 год 10 хв");

    fireEvent.click(within(group).getByRole("button", { name: "Весь період" }));
    expect(screen.getByTestId("probe-y-scale")).toHaveTextContent('"mode":"full"');

    fireEvent.click(within(group).getByRole("button", { name: "Вручну" }));
    fireEvent.change(screen.getByLabelText("мін °C"), { target: { value: "20" } });
    fireEvent.change(screen.getByLabelText("макс °C"), { target: { value: "30,5" } });
    expect(screen.getByTestId("probe-y-scale")).toHaveTextContent('"min":20');
    expect(screen.getByTestId("probe-y-scale")).toHaveTextContent('"max":30.5');
  });

  it("hides the interval line when the whole period is shown", () => {
    const scene = createBenchmarkScene(1);
    render(
      <ChartShell
        title="Температура"
        context="Огляд"
        selectedRange="1 год"
        series={scene.series}
        inspection={null}
        onToggleSeries={vi.fn()}
        onSoloSeries={vi.fn()}
        onResetZoom={vi.fn()}
        locale="uk"
      >
        <Probe visible={scene.xDomain} full={scene.xDomain} />
      </ChartShell>,
    );
    expect(screen.queryByTestId("chart-visible-window")).toBeNull();
  });

  it("formats window durations compactly", () => {
    expect(formatChartWindowDuration(70 * 60_000)).toBe("1 год 10 хв");
    expect(formatChartWindowDuration(3 * 86_400_000 + 4 * 3_600_000)).toBe("3 дн 4 год");
    expect(formatChartWindowDuration(45_000)).toBe("45 с");
    expect(formatChartWindowDuration(7 * 86_400_000, "en")).toBe("7 d");
  });
});

describe("#1868 one shared show-all control", () => {
  it("appears only while a series is hidden and restores every series through one callback", () => {
    const scene = createBenchmarkScene(3);
    const onShowAllSeries = vi.fn();
    const { rerender } = render(
      <ChartShell
        title="Графік"
        context="°C"
        selectedRange="1 год"
        series={scene.series}
        inspection={null}
        onToggleSeries={vi.fn()}
        onSoloSeries={vi.fn()}
        onShowAllSeries={onShowAllSeries}
        onResetZoom={vi.fn()}
        locale="uk"
      >
        <div>plot</div>
      </ChartShell>,
    );
    expect(screen.queryByRole("button", { name: "Повернути всі" })).toBeNull();
    const soloed = scene.series.map((series, index) => ({ ...series, visible: index === 0 }));
    rerender(
      <ChartShell
        title="Графік"
        context="°C"
        selectedRange="1 год"
        series={soloed}
        inspection={null}
        onToggleSeries={vi.fn()}
        onSoloSeries={vi.fn()}
        onShowAllSeries={onShowAllSeries}
        onResetZoom={vi.fn()}
        locale="uk"
      >
        <div>plot</div>
      </ChartShell>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Повернути всі" }));
    expect(onShowAllSeries).toHaveBeenCalledTimes(1);
  });
});
