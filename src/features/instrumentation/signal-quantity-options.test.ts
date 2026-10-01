import { describe, expect, it } from "vitest";

import {
  findSignalQuantity,
  suggestSignalBusinessKey,
  unitForSignalQuantity,
} from "./signal-quantity-options";

describe("signal quantity choices", () => {
  it("offers only proven registry units for process-neutral quantities", () => {
    expect(findSignalQuantity("pressure")?.units.map((unit) => unit.value)).toEqual(["bar", "kPa"]);
    expect(findSignalQuantity("temperature")?.units.map((unit) => unit.value)).toEqual(["degC"]);
    expect(findSignalQuantity("relative_humidity")?.units.map((unit) => unit.value)).toEqual(["%RH"]);
    expect(findSignalQuantity("suction_pressure")).toBeUndefined();
    expect(findSignalQuantity("custom_quantity")).toBeUndefined();
  });

  it("requires an explicit pressure unit and never converts a previous temperature unit", () => {
    expect(unitForSignalQuantity("pressure", "degC")).toBe("");
    expect(unitForSignalQuantity("pressure", "kPa")).toBe("kPa");
    expect(unitForSignalQuantity("temperature", "bar")).toBe("degC");
    expect(unitForSignalQuantity("relative_humidity", "bar")).toBe("%RH");
    expect(unitForSignalQuantity("unknown", "bar")).toBe("");
  });
});

describe("new signal business-key suggestion", () => {
  it.each([
    { quantity: "pressure", keys: [], expected: "pressure" },
    { quantity: "pressure", keys: ["pressure"], expected: "pressure.2" },
    { quantity: "pressure", keys: ["pressure", "pressure.2"], expected: "pressure.3" },
    { quantity: "pressure", keys: ["PRESSURE", "pressure.2", "pressure.4"], expected: "pressure.3" },
    { quantity: "relative_humidity", keys: ["pressure"], expected: "relative_humidity" },
    { quantity: "custom_quantity", keys: [], expected: "custom_quantity" },
  ])("suggests a unique process-neutral key for $quantity", ({ quantity, keys, expected }) => {
    expect(suggestSignalBusinessKey(quantity, keys)).toBe(expected);
  });

  it.each(["", "Pressure", "pressure with spaces", "1pressure", "p".repeat(65)])(
    "does not guess a key for malformed or unbounded input: %s",
    (quantity) => expect(suggestSignalBusinessKey(quantity, [])).toBe(""),
  );
});
