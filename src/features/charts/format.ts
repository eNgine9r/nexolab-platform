import type { ChartXDomain } from "./domain";

const DEFAULT_CHART_FRACTION_DIGITS = 2;

export interface ChartTimestampFormatOptions {
  locale?: string;
  timeZone?: string;
}

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

function timestampDate(timestampMs: number): Date | null {
  if (!Number.isFinite(timestampMs)) return null;
  const value = new Date(timestampMs);
  return Number.isFinite(value.getTime()) ? value : null;
}

export function formatChartExactTimestamp(
  timestampMs: number,
  options: ChartTimestampFormatOptions = {},
): string {
  const value = timestampDate(timestampMs);
  if (!value) return "—";
  return new Intl.DateTimeFormat(options.locale ?? "uk-UA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
    ...(options.timeZone ? { timeZone: options.timeZone } : {}),
  }).format(value);
}

export function formatChartAxisTimestamp(
  timestampMs: number,
  domain: ChartXDomain,
  options: ChartTimestampFormatOptions = {},
): string {
  const value = timestampDate(timestampMs);
  if (!value) return "—";
  const spanMs = Math.max(0, domain.toMs - domain.fromMs);
  const shortWindow = spanMs <= 6 * 60 * 60 * 1_000;
  return new Intl.DateTimeFormat(options.locale ?? "uk-UA", {
    ...(shortWindow ? {} : { day: "2-digit", month: "2-digit" }),
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    ...(options.timeZone ? { timeZone: options.timeZone } : {}),
  }).format(value);
}
