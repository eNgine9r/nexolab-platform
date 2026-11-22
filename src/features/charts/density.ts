/**
 * User-selectable chart detail (point density), #1620 / WP-E.
 *
 * The value is a MAXIMUM rendered-points budget per series — never the number of physical
 * measurements, never a change of acquisition, never an interpolation. The shared
 * evidence-preserving reducer still keeps first/last points, per-bucket min/max, explicit
 * gap boundaries and pinned evidence (it may exceed the budget to keep them).
 *
 * Because the cost of a plot is roughly proportional to the TOTAL number of rendered points
 * (series × points), every mode is subject to an aggregate cap so that e.g. 5 000 points ×
 * 24 series can never be requested. Cap values derive from the Raspberry Pi ARM64 paired
 * measurements recorded in docs/architecture/nexolab-chart-system.md §14.2/§14.5.
 */

import { CHART_POINT_BUDGET_DEFAULT } from "./point-budget";

export const CHART_DENSITY_MODES = ["auto", 250, 500, 1000, 2500, 5000] as const;
export type ChartDensityMode = (typeof CHART_DENSITY_MODES)[number];

/** Total rendered points across all plotted series that the Auto mode may reach. */
export const CHART_AUTO_AGGREGATE_POINTS = 3_840;
/** Hard ceiling of total rendered points across all plotted series for any manual mode. */
export const CHART_AGGREGATE_POINT_CAP = 6_000;
/** Auto never drops below this per series (readability floor), nor exceeds the accepted default. */
export const CHART_AUTO_MINIMUM_POINTS = 100;

export interface ChartPointBudgetResolution {
  /** Maximum rendered points per series after applying the aggregate cap. */
  perSeries: number;
  /** What the operator asked for (Auto resolves to its own target). */
  requested: number;
  /** True when the aggregate cap lowered the requested per-series budget. */
  capped: boolean;
  /** Total budget across all series (`perSeries × seriesCount`). */
  aggregate: number;
}

export function isChartDensityMode(value: unknown): value is ChartDensityMode {
  return (CHART_DENSITY_MODES as readonly unknown[]).includes(value);
}

export function chartDensityLabel(mode: ChartDensityMode): string {
  return mode === "auto" ? "Авто" : mode.toLocaleString("uk-UA");
}

/**
 * Resolves the per-series budget for `seriesCount` plotted series. Deterministic and pure.
 */
export function resolveChartPointBudget(
  mode: ChartDensityMode,
  seriesCount: number,
): ChartPointBudgetResolution {
  const count = Math.max(1, Math.floor(Number.isFinite(seriesCount) ? seriesCount : 1));
  if (mode === "auto") {
    const perSeries = Math.max(
      CHART_AUTO_MINIMUM_POINTS,
      Math.min(CHART_POINT_BUDGET_DEFAULT, Math.floor(CHART_AUTO_AGGREGATE_POINTS / count)),
    );
    return { perSeries, requested: perSeries, capped: false, aggregate: perSeries * count };
  }
  const allowed = Math.max(CHART_AUTO_MINIMUM_POINTS, Math.floor(CHART_AGGREGATE_POINT_CAP / count));
  const perSeries = Math.min(mode, allowed);
  return { perSeries, requested: mode, capped: perSeries < mode, aggregate: perSeries * count };
}

const STORAGE_KEY_PREFIX = "nexolab:chart-density:";

/** Per-surface local preference; storage failures (private mode, blocked) fall back to Auto. */
export function readStoredChartDensity(surface: string): ChartDensityMode {
  try {
    const raw = globalThis.localStorage?.getItem(STORAGE_KEY_PREFIX + surface);
    if (raw === null || raw === undefined) return "auto";
    const parsed: unknown = raw === "auto" ? "auto" : Number(raw);
    return isChartDensityMode(parsed) ? parsed : "auto";
  } catch {
    return "auto";
  }
}

export function storeChartDensity(surface: string, mode: ChartDensityMode): void {
  try {
    globalThis.localStorage?.setItem(STORAGE_KEY_PREFIX + surface, String(mode));
  } catch {
    // The preference is a convenience only.
  }
}
