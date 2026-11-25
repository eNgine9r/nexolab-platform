import { describe, expect, it, vi } from "vitest";
import { buildOverviewSensorHierarchy } from "./overview-sensor-hierarchy";
import { overviewCatalogFixture } from "./overview-sensor-test-fixtures";
import { readOverviewSensorCatalog } from "./use-overview-sensor-catalog";

describe("Overview sensor identity", () => {
  it("groups by verified device, shows chamber only as context and retains every unique channel", () => {
    const groups = buildOverviewSensorHierarchy(["106-03", "106-04", "106-03", "199-01"], "edge-01", [
      overviewCatalogFixture(),
    ]);
    expect(groups.map((group) => group.label)).toEqual(["Контролер К106", "Прилад не підтверджено"]);
    expect(groups[0]).toMatchObject({
      label: "Контролер К106",
      context: "Камера №2",
      sensors: [
        { channelId: "106-03", label: "Повітря" },
        { channelId: "106-04", label: "Продукт" },
      ],
    });
    expect(groups[1]).toMatchObject({
      id: "unconfirmed",
      sensors: [{ channelId: "199-01", label: "199-01" }],
    });
    expect(groups.flatMap((group) => group.sensors.map((sensor) => sensor.channelId))).toEqual([
      "106-03",
      "106-04",
      "199-01",
    ]);
  });

  it.each(["wrong-node", "wrong-device", "wrong-unit", "ambiguous-bus"])(
    "keeps %s unconfirmed without inventing a chamber or controller",
    (kind) => {
      const fixture = overviewCatalogFixture();
      const catalog = [fixture];
      if (kind === "wrong-node") fixture.climateChamber.transportNodeId = "other-edge";
      if (kind === "wrong-device") fixture.temperatureChannels[0]!.deviceId = "other-device";
      if (kind === "wrong-unit") fixture.temperatureControllers[0]!.unitId = 107;
      if (kind === "ambiguous-bus")
        catalog.push({
          ...overviewCatalogFixture(),
          climateChamber: { ...fixture.climateChamber, id: "other-camera", busId: "other-bus" },
        });
      const groups = buildOverviewSensorHierarchy(["106-03"], "edge-01", catalog);
      expect(groups[0]).toMatchObject({
        id: "unconfirmed",
        label: "Прилад не підтверджено",
        sensors: [{ channelId: "106-03", label: "106-03" }],
      });
      expect(groups[0]?.context).toBeUndefined();
    },
  );

  it("preserves the same verified device across multiple chamber contexts", () => {
    const first = overviewCatalogFixture();
    const second = overviewCatalogFixture();
    first.temperatureChannels = [first.temperatureChannels[0]!];
    second.temperatureChannels = [second.temperatureChannels[1]!];
    second.climateChamber.id = "camera-3";
    second.climateChamber.name = "Камера №3";

    const groups = buildOverviewSensorHierarchy(["106-03", "106-04"], "edge-01", [first, second]);
    expect(groups).toHaveLength(1);
    expect(groups[0]?.label).toBe("Контролер К106");
    expect(groups[0]?.context).toBe("Камера №2 · Камера №3");
    expect(groups[0]?.sensors.map((sensor) => sensor.channelId)).toEqual(["106-03", "106-04"]);
  });

  it("does not join same controller IDs on different buses or across nodes", () => {
    const first = overviewCatalogFixture();
    const second = overviewCatalogFixture();
    first.temperatureChannels = [first.temperatureChannels[0]!];
    second.temperatureChannels = [second.temperatureChannels[1]!];
    second.climateChamber.id = "camera-3";
    second.climateChamber.busId = "other-bus";
    const groups = buildOverviewSensorHierarchy(["106-03", "106-04"], "edge-01", [first, second]);
    expect(groups).toHaveLength(2);
    expect(groups[0]?.id).not.toEqual(groups[1]?.id);
    const missingNode = buildOverviewSensorHierarchy(["106-03"], null, [first, second]);
    expect(missingNode[0]?.id).toBe("unconfirmed");
  });
});

describe("read-only catalog loading", () => {
  it("reads only chambers on the actual transport node", async () => {
    const fixture = overviewCatalogFixture();
    const getEquipment = vi.fn(async () => fixture);
    const result = await readOverviewSensorCatalog(
      {
        listChambers: async () => [
          fixture.climateChamber,
          { ...fixture.climateChamber, id: "other", transportNodeId: "other" },
        ],
        getEquipment,
      },
      "edge-01",
      new AbortController().signal,
    );
    expect(result).toEqual([fixture]);
    expect(getEquipment).toHaveBeenCalledExactlyOnceWith("camera-2");
  });
  it("rejects mismatched camera identity rather than applying its names", async () => {
    const fixture = overviewCatalogFixture();
    await expect(
      readOverviewSensorCatalog(
        {
          listChambers: async () => [fixture.climateChamber],
          getEquipment: async () => ({
            ...fixture,
            climateChamber: { ...fixture.climateChamber, busId: "wrong" },
          }),
        },
        "edge-01",
        new AbortController().signal,
      ),
    ).rejects.toThrow("не підтверджено");
  });
  it("does not treat a partial catalog failure as a complete unique mapping", async () => {
    const fixture = overviewCatalogFixture();
    await expect(
      readOverviewSensorCatalog(
        {
          listChambers: async () => [fixture.climateChamber, { ...fixture.climateChamber, id: "failed" }],
          getEquipment: async (id) => {
            if (id === "failed") throw new Error("unavailable");
            return fixture;
          },
        },
        "edge-01",
        new AbortController().signal,
      ),
    ).rejects.toThrow("unavailable");
  });
  it("stops before reading equipment when aborted", async () => {
    const fixture = overviewCatalogFixture();
    const controller = new AbortController();
    controller.abort();
    const getEquipment = vi.fn(async () => fixture);
    await expect(
      readOverviewSensorCatalog(
        { listChambers: async () => [fixture.climateChamber], getEquipment },
        "edge-01",
        controller.signal,
      ),
    ).rejects.toThrow();
    expect(getEquipment).not.toHaveBeenCalled();
  });
});
