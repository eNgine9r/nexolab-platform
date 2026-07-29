import { describe, expect, it } from "vitest";

import { refrigerationEquipment } from "@/data/refrigeration";

import { createEquipmentCopyDraft } from "./equipment-copy";

describe("createEquipmentCopyDraft", () => {
  it("copies reusable passport fields while clearing identity and operational ownership", () => {
    const source = refrigerationEquipment[0];
    const draft = createEquipmentCopyDraft(source, refrigerationEquipment);

    expect(draft).toMatchObject({
      name: `${source.name} — копія`,
      code: `${source.code}-COPY`,
      location: source.location,
      laboratory: source.laboratory ?? "",
      zone: source.zone ?? "",
      type: source.type,
      manufacturer: source.manufacturer,
      model: source.model,
      temperatureClass: source.temperatureClass,
      totalSensors: source.totalSensors,
      lifecycleStatus: "active",
      nodeId: "",
      serialNumber: "",
      installedAt: "",
      servicedAt: "",
    });
  });

  it("increments suggested names and codes without case-sensitive collisions", () => {
    const source = refrigerationEquipment[0];
    const existing = [
      ...refrigerationEquipment,
      { ...source, id: "copy-1", name: `${source.name} — КОПІЯ`, code: `${source.code}-copy` },
      { ...source, id: "copy-2", name: `${source.name} — копія 2`, code: `${source.code}-COPY-2` },
    ];

    expect(createEquipmentCopyDraft(source, existing)).toMatchObject({
      name: `${source.name} — копія 3`,
      code: `${source.code}-COPY-3`,
    });
  });
});
