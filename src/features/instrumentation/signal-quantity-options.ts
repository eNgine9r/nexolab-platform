export const SIGNAL_QUANTITIES = [
  {
    value: "temperature",
    label: "Температура",
    units: [{ value: "degC", label: "°C" }],
  },
  {
    value: "pressure",
    label: "Тиск",
    units: [
      { value: "bar", label: "бар" },
      { value: "kPa", label: "кПа" },
    ],
  },
  {
    value: "relative_humidity",
    label: "Відносна вологість",
    units: [{ value: "%RH", label: "% RH" }],
  },
] as const;

export function findSignalQuantity(value: string) {
  return SIGNAL_QUANTITIES.find((quantity) => quantity.value === value);
}

export function unitForSignalQuantity(quantity: string, previousUnit: string): string {
  const option = findSignalQuantity(quantity);
  if (!option) return "";
  if (option.units.some((unit) => unit.value === previousUnit)) return previousUnit;
  return option.units.length === 1 ? option.units[0].value : "";
}

export function suggestSignalBusinessKey(quantity: string, existingKeys: readonly string[]): string {
  const base = quantity.trim();
  if (!/^[a-z][a-z0-9_.-]{0,63}$/.test(base)) return "";
  const existing = new Set(existingKeys.map((key) => key.trim().toLowerCase()));
  if (!existing.has(base)) return base;
  for (let suffix = 2; suffix <= existing.size + 2; suffix++) {
    const candidate = `${base}.${suffix}`;
    if (!existing.has(candidate)) return candidate;
  }
  return "";
}
