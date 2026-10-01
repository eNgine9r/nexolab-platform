export function formatOperationalTimestamp(
  value: string | number | Date | null | undefined,
  timeZone: string,
  options: Intl.DateTimeFormatOptions = { dateStyle: "short", timeStyle: "medium" },
  fallback = "—",
  locale = "uk-UA",
): string {
  if (value === null || value === undefined || value === "") return fallback;
  const date = value instanceof Date ? value : new Date(value);
  if (!Number.isFinite(date.getTime())) return fallback;
  try {
    return `${new Intl.DateTimeFormat(locale, { ...options, timeZone }).format(date)} (${timeZone})`;
  } catch {
    return fallback;
  }
}
