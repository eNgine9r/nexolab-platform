/** Read-only projection of canonical polling eligibility, never historical inventory. */
export const TEMPERATURE_REGISTRY_URL = "/api/device-agent/acquisition-registry";

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Некоректна конфігурація реєстру збору даних.");
  }
  return value as Record<string, unknown>;
}

function indexed(value: unknown, key: string): Map<string, Record<string, unknown>> {
  if (!Array.isArray(value)) throw new Error("Реєстр збору даних не містить обов’язкових списків.");
  const result = new Map<string, Record<string, unknown>>();
  for (const entry of value) {
    const item = record(entry);
    const id = item[key];
    if (typeof id !== "string" || !id || result.has(id)) {
      throw new Error("Реєстр збору даних містить некоректні або дубльовані ідентифікатори.");
    }
    result.set(id, item);
  }
  return result;
}

export function monitoredTemperatureChannels(value: unknown): string[] {
  const root = record(value);
  if (root.schema_version !== 2 || !Number.isInteger(root.revision) || Number(root.revision) < 1) {
    throw new Error("Непідтримувана версія реєстру збору даних.");
  }
  const buses = indexed(root.buses, "bus_id");
  const devices = indexed(root.devices, "device_id");
  const targets = indexed(root.targets, "target_id");
  const channels = new Set<string>();
  for (const target of targets.values()) {
    const device = devices.get(String(target.device_id));
    if (!device) throw new Error("Канал реєстру не має підтвердженого приладу.");
    if (device.device_family !== "xjp60d") continue;
    const bus = buses.get(String(device.bus_id));
    if (
      device.lifecycle !== "active" ||
      target.lifecycle !== "active" ||
      target.poll_eligible !== true ||
      target.function !== 3 ||
      bus?.read_only !== true ||
      bus.protocol !== "modbus_rtu"
    )
      continue;
    const unit = device.unit_id;
    if (typeof unit !== "number" || !Number.isInteger(unit) || unit < 1 || unit > 247) continue;
    if (target.metric !== "temperature.probe" || target.unit !== "degC") continue;
    const channel = target.telemetry_channel_id;
    if (typeof channel !== "string") continue;
    const section = /^([a-zA-Z0-9_-]+):([1-9]\d{0,2})-S0([1-6])$/.exec(channel);
    const legacy = /^([1-9]\d{0,2})-0([1-6])$/.exec(channel);
    const sectionMatches =
      section &&
      section[1] === device.bus_id &&
      Number(section[2]) === unit &&
      device.device_id === `xjp60d-sections:${device.bus_id}:${unit}` &&
      target.target_id === `${device.device_id}-S0${section[3]}`;
    const legacyMatches =
      legacy &&
      Number(legacy[1]) === unit &&
      device.device_id === `xjp60d-${unit}` &&
      target.target_id === `xjp60d:${channel}`;
    if (!sectionMatches && !legacyMatches) continue;
    if (channels.has(channel)) throw new Error("Неоднозначна прив’язка температурного каналу.");
    channels.add(channel);
  }
  return [...channels].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
}
