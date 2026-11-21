/**
 * `<input type="datetime-local">` carries a wall-clock value without a zone.
 * Operators read every chart in the configured display time zone, so custom
 * ranges must be interpreted in that zone, not in the browser's local zone.
 */

const PATTERN = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/;

function zoneParts(timestampMs: number, timeZone: string): Record<string, number> {
  const formatter = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  const parts: Record<string, number> = {};
  for (const part of formatter.formatToParts(new Date(timestampMs))) {
    if (part.type !== "literal") parts[part.type] = Number(part.value);
  }
  return parts;
}

function zoneOffsetMs(timestampMs: number, timeZone: string): number {
  const parts = zoneParts(timestampMs, timeZone);
  const asUtc = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour % 24, parts.minute, parts.second);
  return asUtc - Math.floor(timestampMs / 1000) * 1000;
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

export function toZonedInputValue(timestampMs: number, timeZone: string): string {
  if (!Number.isFinite(timestampMs)) return "";
  const parts = zoneParts(timestampMs, timeZone);
  return `${parts.year}-${pad(parts.month)}-${pad(parts.day)}T${pad(parts.hour % 24)}:${pad(parts.minute)}`;
}

/**
 * Converts a zone-less wall-clock value to an instant in `timeZone`.
 * Returns null for malformed input and for wall-clock times skipped by a DST jump.
 * For an ambiguous (repeated) hour the earlier instant is chosen.
 */
export function fromZonedInputValue(value: string, timeZone: string): number | null {
  const match = PATTERN.exec(value.trim());
  if (!match) return null;
  const [, year, month, day, hour, minute, second] = match;
  const wallAsUtc = Date.UTC(
    Number(year),
    Number(month) - 1,
    Number(day),
    Number(hour),
    Number(minute),
    Number(second ?? 0),
  );
  if (!Number.isFinite(wallAsUtc)) return null;
  const candidates = new Set<number>();
  for (const probe of [wallAsUtc - 86_400_000, wallAsUtc, wallAsUtc + 86_400_000]) {
    candidates.add(wallAsUtc - zoneOffsetMs(probe, timeZone));
  }
  const matches = [...candidates]
    .filter((candidate) => toZonedInputValue(candidate, timeZone) === value.trim().slice(0, 16))
    .sort((left, right) => left - right);
  return matches[0] ?? null;
}
