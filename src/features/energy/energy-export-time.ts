const ZONE = "Europe/Kyiv";
const wallFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});
const offsetFormatter = new Intl.DateTimeFormat("en-US", {
  timeZone: ZONE,
  timeZoneName: "longOffset",
});

function parts(value: number) {
  return Object.fromEntries(
    wallFormatter.formatToParts(new Date(value)).map((part) => [part.type, part.value]),
  );
}

export function kyivInput(value: string | number): string {
  const at = typeof value === "number" ? value : Date.parse(value);
  if (!Number.isFinite(at)) return "";
  const result = parts(at);
  return `${result.year}-${result.month}-${result.day}T${result.hour}:${result.minute}:${result.second}`;
}

function offsetSeconds(value: number): number | null {
  const text = offsetFormatter
    .formatToParts(new Date(value))
    .find((part) => part.type === "timeZoneName")?.value;
  if (text === "GMT") return 0;
  const match = text?.match(/^GMT([+-])(\d{2}):(\d{2})(?::(\d{2}))?$/);
  if (!match) return null;
  return (match[1] === "+" ? 1 : -1) * (+match[2] * 3600 + +match[3] * 60 + +(match[4] ?? 0));
}

export type KyivOccurrence = { utc: string; offset: string };
export type KyivTimeResult = {
  kind: "invalid" | "nonexistent" | "ambiguous" | "resolved";
  occurrences: KyivOccurrence[];
};

export function resolveKyivInput(value: string): KyivTimeResult {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/);
  if (!match || +match[1] < 1970) return { kind: "invalid", occurrences: [] };
  const canonical = `${match[1]}-${match[2]}-${match[3]}T${match[4]}:${match[5]}:${match[6] ?? "00"}`;
  const wall = Date.parse(canonical + "Z");
  if (!Number.isFinite(wall) || new Date(wall).toISOString().slice(0, 19) !== canonical) {
    return { kind: "invalid", occurrences: [] };
  }
  const offsets = new Set([-86400000, 0, 86400000].map((delta) => offsetSeconds(wall + delta)));
  const occurrences = [...offsets]
    .filter((offset): offset is number => offset !== null)
    .map((offset) => ({ at: wall - offset * 1000, offset }))
    .filter(({ at }) => kyivInput(at) === canonical)
    .sort((a, b) => a.at - b.at)
    .map(({ at, offset }) => ({
      utc: new Date(at).toISOString(),
      offset: `${offset >= 0 ? "+" : "-"}${String(Math.floor(Math.abs(offset) / 3600)).padStart(2, "0")}:${String(Math.floor((Math.abs(offset) % 3600) / 60)).padStart(2, "0")}`,
    }));
  return {
    kind: occurrences.length === 0 ? "nonexistent" : occurrences.length > 1 ? "ambiguous" : "resolved",
    occurrences,
  };
}

export function selectedKyivTime(value: string, occurrence: string): string | null {
  const result = resolveKyivInput(value);
  if (result.kind === "resolved") return result.occurrences[0].utc;
  if (result.kind === "ambiguous")
    return result.occurrences.find((item) => item.utc === occurrence)?.utc ?? null;
  return null;
}

export function kyivLabel(value: string): string {
  const at = Date.parse(value);
  if (!Number.isFinite(at)) return "—";
  const local = kyivInput(at).replace("T", " ");
  const offset =
    offsetFormatter.formatToParts(new Date(at)).find((part) => part.type === "timeZoneName")?.value ?? "";
  return `${local} ${offset}`;
}
