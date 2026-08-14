const DEFAULT_CHART_FRACTION_DIGITS = 2;

export function chartDisplayPrecision(precision?: number): number {
  if (precision === undefined) return DEFAULT_CHART_FRACTION_DIGITS;
  if (!Number.isInteger(precision) || precision < 0 || precision > 12) {
    throw new Error("Chart display precision must be an integer between 0 and 12");
  }
  return precision;
}

export function formatChartValue(value: number, precision?: number): string {
  if (!Number.isFinite(value)) return "—";
  return value.toFixed(chartDisplayPrecision(precision));
}
