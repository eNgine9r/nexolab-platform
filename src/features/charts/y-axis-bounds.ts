import { chartSeriesKey, type ChartSeries, type ChartThreshold, type ChartXDomain } from "./domain";
import { chartDisplayPrecision } from "./format";
import type { ChartYAxisModel } from "./units";

/**
 * Y-axis scaling of a chart (#1843).
 *
 * - `auto` (default): every physical quantity's axis fits the measurements visible in the current
 *   time window, so a zoom into one hour shows that hour's variation instead of the whole period.
 * - `full`: the axis fits the whole selected period and stays put while zooming and panning.
 * - `manual`: operator min/max per axis; a missing side falls back to `auto`.
 *
 * Hidden series never influence an axis. Nothing is interpolated or changed in the data: the axis
 * only follows what is drawn (including the part of a line that enters the window from a point
 * just outside it).
 */
export type ChartYScaleMode = "auto" | "full" | "manual";

export interface ChartManualYBounds {
  min?: number;
  max?: number;
}

export interface ChartYScale {
  mode: ChartYScaleMode;
  /** Manual bounds by Y-axis id (one axis per physical quantity and unit). */
  manual?: Readonly<Record<string, ChartManualYBounds>>;
}

export const DEFAULT_CHART_Y_SCALE: ChartYScale = { mode: "auto" };

export interface ChartOffScaleThreshold {
  id: string;
  label: string;
  value: number;
  direction: "above" | "below";
}

export interface ChartYAxisBounds {
  axisId: string;
  min: number;
  max: number;
  interval: number;
  /** Extent of the drawn measurements the bounds were fitted to (null: no data, kept or default). */
  dataMin: number | null;
  dataMax: number | null;
  offScaleThresholds: readonly ChartOffScaleThreshold[];
}

/** Fraction of the data span added above and below (never less than one tick). */
const PADDING_FRACTION = 0.06;
const TARGET_TICKS = 5;
/** Below this many display-resolution steps a span is noise: the axis is not stretched further. */
const MINIMUM_RESOLUTION_STEPS = 5;
/** Thresholds this far (in data spans) outside the data are pulled into view; farther ones are flagged. */
const THRESHOLD_REACH_SPANS = 1;
/** New data still filling at least this share of the current axis keeps it (no axis jitter). */
const KEEP_FILL_RATIO = 0.6;

function lowerBound(points: ChartSeries["segments"][number]["points"], timestampMs: number): number {
  let low = 0;
  let high = points.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (points[middle].timestampMs < timestampMs) low = middle + 1;
    else high = middle;
  }
  return low;
}

function interpolate(
  left: { timestampMs: number; value: number },
  right: { timestampMs: number; value: number },
  timestampMs: number,
): number {
  const span = right.timestampMs - left.timestampMs;
  if (span <= 0) return left.value;
  return left.value + ((right.value - left.value) * (timestampMs - left.timestampMs)) / span;
}

/**
 * Min/max of what a series draws inside `domain`: its points in the window plus the values where
 * a line crosses the window edges (only within one continuous segment). Points are time-ordered
 * within a segment, so the window is found by binary search.
 */
export function visibleSeriesExtent(
  series: ChartSeries,
  domain: ChartXDomain,
): { min: number; max: number } | null {
  let min = Infinity;
  let max = -Infinity;
  const take = (value: number) => {
    if (!Number.isFinite(value)) return;
    if (value < min) min = value;
    if (value > max) max = value;
  };
  for (const segment of series.segments) {
    const points = segment.points;
    if (points.length === 0) continue;
    if (points[points.length - 1].timestampMs < domain.fromMs || points[0].timestampMs > domain.toMs)
      continue;
    const start = lowerBound(points, domain.fromMs);
    let index = start;
    for (; index < points.length && points[index].timestampMs <= domain.toMs; index += 1) {
      take(points[index].value);
    }
    // Where the line enters and leaves the window. This also covers a line that crosses the
    // whole window with no point inside it (deep zoom between two measurements).
    if (start > 0 && start < points.length)
      take(interpolate(points[start - 1], points[start], domain.fromMs));
    if (index > 0 && index < points.length) take(interpolate(points[index - 1], points[index], domain.toMs));
  }
  return min === Infinity ? null : { min, max };
}

function niceStep(rawStep: number): number {
  const exponent = Math.floor(Math.log10(rawStep));
  const base = 10 ** exponent;
  const fraction = rawStep / base;
  const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 2.5 ? 2.5 : fraction <= 5 ? 5 : 10;
  return nice * base;
}

function roundToStep(value: number, step: number): number {
  // Removes binary noise such as 24.900000000000002 from tick-aligned bounds.
  const decimals = Math.max(0, -Math.floor(Math.log10(step)) + 2);
  return Number(value.toFixed(Math.min(decimals, 12)));
}

/**
 * Readable bounds around [dataMin, dataMax]: padding, a span no smaller than the display
 * resolution allows, and min/max aligned to a 1/2/2.5/5 × 10ⁿ tick step. Negative and constant
 * ranges are handled; zero is not forced into the range.
 */
export function niceYAxisBounds(
  dataMin: number,
  dataMax: number,
  options: { resolution?: number } = {},
): { min: number; max: number; interval: number } {
  const low = Math.min(dataMin, dataMax);
  const high = Math.max(dataMin, dataMax);
  const magnitude = Math.max(Math.abs(low), Math.abs(high));
  const resolutionSpan = (options.resolution ?? 0) * MINIMUM_RESOLUTION_STEPS;
  const constantSpan = magnitude > 0 ? magnitude * 0.04 : 2;
  let span = high - low;
  if (span < resolutionSpan) span = resolutionSpan;
  if (!(span > 0)) span = constantSpan;
  const center = (low + high) / 2;
  const paddedLow = Math.min(low, center - span / 2) - span * PADDING_FRACTION;
  const paddedHigh = Math.max(high, center + span / 2) + span * PADDING_FRACTION;
  const step = niceStep((paddedHigh - paddedLow) / TARGET_TICKS);
  return {
    min: roundToStep(Math.floor(paddedLow / step) * step, step),
    max: roundToStep(Math.ceil(paddedHigh / step) * step, step),
    interval: step,
  };
}

function seriesResolution(series: readonly ChartSeries[]): number {
  // The finest display precision of the axis' series; 2 decimals when none is declared.
  const precision = Math.max(0, ...series.map((item) => chartDisplayPrecision(item.displayPrecision)));
  return 10 ** -precision;
}

export function chartYScaleKey(scale: ChartYScale | undefined): string {
  if (!scale || scale.mode === "auto") return "auto";
  if (scale.mode === "full") return "full";
  return `manual:${JSON.stringify(scale.manual ?? {})}`;
}

/**
 * Bounds of every visible Y axis for the visible window (`auto`), the whole period (`full`) or
 * operator bounds (`manual`). `previous` bounds are kept while the new data still fills most of
 * them, so live samples and small pans do not make the axis jump.
 */
export function computeChartYAxisBounds({
  series,
  axisModel,
  visibleDomain,
  fullDomain,
  scale = DEFAULT_CHART_Y_SCALE,
  thresholds = [],
  previous,
}: {
  series: readonly ChartSeries[];
  axisModel: ChartYAxisModel;
  visibleDomain: ChartXDomain;
  fullDomain: ChartXDomain;
  scale?: ChartYScale;
  thresholds?: readonly ChartThreshold[];
  previous?: ReadonlyMap<string, ChartYAxisBounds>;
}): Map<string, ChartYAxisBounds> {
  const result = new Map<string, ChartYAxisBounds>();
  const domain = scale.mode === "full" ? fullDomain : visibleDomain;
  const bySeriesKey = new Map(series.map((item) => [chartSeriesKey(item.identity), item] as const));
  for (const axis of axisModel.visibleAxes) {
    const axisSeries = axis.seriesKeys
      .map((key) => bySeriesKey.get(key))
      .filter((item): item is ChartSeries => item !== undefined && item.visible);
    let dataMin = Infinity;
    let dataMax = -Infinity;
    for (const item of axisSeries) {
      const extent = visibleSeriesExtent(item, domain);
      if (!extent) continue;
      dataMin = Math.min(dataMin, extent.min);
      dataMax = Math.max(dataMax, extent.max);
    }
    const hasData = dataMin !== Infinity;
    const axisKeys = new Set(axisSeries.map((item) => chartSeriesKey(item.identity)));
    const axisThresholds = thresholds.filter(
      (threshold) => axisKeys.has(threshold.seriesKey) && Number.isFinite(threshold.value),
    );
    // Thresholds close to the data are pulled into view; distant ones are flagged instead of
    // squashing the measurements into a thin line.
    let fitMin = dataMin;
    let fitMax = dataMax;
    if (hasData) {
      const reach = Math.max(dataMax - dataMin, seriesResolution(axisSeries) * MINIMUM_RESOLUTION_STEPS);
      for (const threshold of axisThresholds) {
        if (threshold.value >= dataMin - reach * THRESHOLD_REACH_SPANS && threshold.value < fitMin)
          fitMin = threshold.value;
        if (threshold.value <= dataMax + reach * THRESHOLD_REACH_SPANS && threshold.value > fitMax)
          fitMax = threshold.value;
      }
    }
    const previousBounds = previous?.get(axis.id);
    let bounds: { min: number; max: number; interval: number } | null = null;
    if (hasData) {
      const fitted = niceYAxisBounds(fitMin, fitMax, { resolution: seriesResolution(axisSeries) });
      const keep =
        previousBounds &&
        scale.mode !== "manual" &&
        previousBounds.min <= fitMin &&
        previousBounds.max >= fitMax &&
        fitted.max - fitted.min >= (previousBounds.max - previousBounds.min) * KEEP_FILL_RATIO;
      bounds = keep
        ? { min: previousBounds.min, max: previousBounds.max, interval: previousBounds.interval }
        : fitted;
    } else if (previousBounds) {
      // Nothing drawn in this window (gap, not loaded yet): keep the axis instead of collapsing it.
      bounds = { min: previousBounds.min, max: previousBounds.max, interval: previousBounds.interval };
    }
    const manual = scale.mode === "manual" ? scale.manual?.[axis.id] : undefined;
    const manualMin = manual?.min !== undefined && Number.isFinite(manual.min) ? manual.min : undefined;
    const manualMax = manual?.max !== undefined && Number.isFinite(manual.max) ? manual.max : undefined;
    if (manualMin !== undefined || manualMax !== undefined) {
      const min = manualMin ?? bounds?.min ?? manualMax! - 1;
      const max = manualMax ?? bounds?.max ?? manualMin! + 1;
      if (max > min) bounds = { min, max, interval: niceStep((max - min) / TARGET_TICKS) };
    }
    if (!bounds) continue;
    const finalBounds = bounds;
    result.set(axis.id, {
      axisId: axis.id,
      ...finalBounds,
      dataMin: hasData ? dataMin : null,
      dataMax: hasData ? dataMax : null,
      offScaleThresholds: axisThresholds
        .filter((threshold) => threshold.value > finalBounds.max || threshold.value < finalBounds.min)
        .map((threshold) => ({
          id: threshold.id,
          label: threshold.label,
          value: threshold.value,
          direction: threshold.value > finalBounds.max ? ("above" as const) : ("below" as const),
        })),
    });
  }
  return result;
}
