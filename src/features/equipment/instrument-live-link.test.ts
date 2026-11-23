import { describe, expect, it } from "vitest";
import type { CommissioningSession } from "./commissioning-repository";
import { instrumentLiveLink } from "./instrument-live-link";

const active = {
  lifecycle: "active",
  profileId: "dixell-xjp60d",
  nodeId: "edge-01",
  unitId: 2,
} as CommissioningSession;

describe("instrument live links", () => {
  it.each([
    ["dixell-xjp60d", "K2"],
    ["f-and-f-le01mp", "LE01MP-2"],
    ["embraco-sync", "EMBRACO-2"],
  ])("uses the canonical activation identity for %s", (profileId, equipment) => {
    const url = new URL(instrumentLiveLink({ ...active, profileId })!, "http://localhost");
    expect(url.pathname).toBe("/live");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      workspace: "explorer",
      node: "edge-01",
      equipment,
    });
  });

  it.each([
    { lifecycle: "draft" },
    { lifecycle: "verified" },
    { lifecycle: "cancelled" },
    { profileId: "unknown" },
    { profileId: "constructor" },
    { profileId: null },
    { nodeId: null },
    { nodeId: "  " },
    { unitId: null },
    { unitId: 0 },
    { unitId: 248 },
    { unitId: 1.5 },
  ] as Partial<CommissioningSession>[])(
    "does not invent readings for incomplete/inactive identity %j",
    (patch) => {
      expect(instrumentLiveLink({ ...active, ...patch })).toBeNull();
    },
  );

  it("encodes the node scope without adding query parameters", () => {
    const url = new URL(
      instrumentLiveLink({ ...active, nodeId: "edge&equipment=other" })!,
      "http://localhost",
    );
    expect(url.searchParams.get("node")).toBe("edge&equipment=other");
    expect(url.searchParams.getAll("equipment")).toEqual(["K2"]);
  });
});

describe("section instrument scope", () => {
  it("opens a distinct physical group, never old K7 history", () => {
    const href = instrumentLiveLink({
      ...active,
      profileId: "dixell-xjp60d-sections-2",
      busId: "rs485-sdm120",
      unitId: 7,
    });
    const url = new URL(href!, "http://localhost");
    expect(url.searchParams.get("equipment")).toBe("XJP60D-S:rs485-sdm120:7");
    expect(url.searchParams.get("node")).toBe("edge-01");
  });
  it("rejects a group that extends beyond unicast addresses or lacks a bus", () => {
    expect(
      instrumentLiveLink({ ...active, profileId: "dixell-xjp60d-sections-6", busId: "bus", unitId: 243 }),
    ).toBeNull();
    expect(instrumentLiveLink({ ...active, profileId: "dixell-xjp60d-sections-6", busId: null })).toBeNull();
  });
});

describe("SDM120M instrument scope", () => {
  it("does not mix newly commissioned telemetry with historic meter readings", () => {
    const busId = "commissioning-0123456789abcdef";
    const url = new URL(
      instrumentLiveLink({ ...active, profileId: "eastron-sdm120m", busId, unitId: 1 })!,
      "http://localhost",
    );
    expect(url.searchParams.get("equipment")).toBe(`SDM120M:${busId}:1`);
    expect(instrumentLiveLink({ ...active, profileId: "eastron-sdm120m", busId: null })).toBeNull();
  });
});

describe("Waveshare instrument scope", () => {
  it("uses a scoped module identity and never invents an attachment state", () => {
    const busId = "commissioning-0123456789abcdef";
    const href = instrumentLiveLink({ ...active, profileId: "waveshare-8ai-b-v3", busId, unitId: 1 });
    expect(new URL(href!, "http://localhost").searchParams.get("equipment")).toBe(`WAVESHARE-8AI:${busId}:1`);
    expect(instrumentLiveLink({ ...active, profileId: "waveshare-8ai-b-v3", busId: null })).toBeNull();
  });
});
