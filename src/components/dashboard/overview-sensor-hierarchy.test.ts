import { describe, expect, it, vi } from "vitest";
import { buildOverviewSensorHierarchy } from "./overview-sensor-hierarchy";
import { overviewCatalogFixture } from "./overview-sensor-test-fixtures";
import { readOverviewSensorCatalog } from "./use-overview-sensor-catalog";

describe("Overview sensor identity", () => {
  it("uses actual camera/device labels and retains every unique monitored channel", () => {
    const groups = buildOverviewSensorHierarchy(["106-03", "106-04", "106-03", "199-01"], "edge-01", [
      overviewCatalogFixture(),
    ]);
    expect(groups.map((group) => group.label)).toEqual(["Камера №2", "Прив’язку до камери не підтверджено"]);
    expect(groups[0]?.children?.[0]).toMatchObject({
      label: "Контролер К106",
      sensors: [
        { channelId: "106-03", label: "Повітря" },
        { channelId: "106-04", label: "Продукт" },
      ],
    });
    expect(groups.flatMap((group) => group.sensors.map((sensor) => sensor.channelId))).toEqual([
      "106-03",
      "106-04",
      "199-01",
    ]);
  });
  it.each(["wrong-node", "wrong-device", "wrong-unit", "ambiguous-bus"])("keeps %s unconfirmed", (kind) => {
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
    expect(buildOverviewSensorHierarchy(["106-03"], "edge-01", catalog)[0]?.id).toBe("unconfirmed");
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
