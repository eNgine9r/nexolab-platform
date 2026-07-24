import { describe, expect, it } from "vitest";

import { getRefrigerationEquipment } from "@/data/refrigeration";

import { HttpRefrigerationLayoutRepository } from "./http-layout-repository";
import { createRefrigerationLayoutRuntime } from "./layout-repository-runtime";
import { InMemoryRefrigerationLayoutRepository } from "./layout-repository";

function equipment() {
  const value = getRefrigerationEquipment("showcase-106-01");
  if (!value) throw new Error("Refrigeration fixture is missing");
  return value;
}

describe("createRefrigerationLayoutRuntime", () => {
  it("uses the deterministic in-memory adapter in demo mode", async () => {
    const runtime = createRefrigerationLayoutRuntime({
      equipment: equipment(),
      mode: "demo",
      actorId: "operator-demo",
    });

    expect(runtime.mode).toBe("demo");
    expect(runtime.repository).toBeInstanceOf(InMemoryRefrigerationLayoutRepository);
    expect(runtime.actorId).toBe("operator-demo");
    expect(runtime.error).toBeNull();

    const draft = await runtime.repository?.getDraft(equipment().id);
    expect(draft).toMatchObject({
      ok: true,
      value: {
        equipmentId: equipment().id,
        version: 1,
        placements: expect.arrayContaining([expect.objectContaining({ sensorId: "sensor-1" })]),
      },
    });
  });

  it("uses the production HTTP adapter in live mode", () => {
    const runtime = createRefrigerationLayoutRuntime({
      equipment: equipment(),
      mode: "live",
      apiBaseUrl: "http://127.0.0.1:8082",
      actorId: "operator-live",
    });

    expect(runtime.mode).toBe("live");
    expect(runtime.repository).toBeInstanceOf(HttpRefrigerationLayoutRepository);
    expect(runtime.actorId).toBe("operator-live");
    expect(runtime.error).toBeNull();
  });

  it("surfaces a configuration error without silently falling back to demo", () => {
    const runtime = createRefrigerationLayoutRuntime({
      equipment: equipment(),
      mode: "live",
      apiBaseUrl: "",
    });

    expect(runtime.mode).toBe("live");
    expect(runtime.repository).toBeNull();
    expect(runtime.error).toMatch(/API URL is required/i);
  });

  it("normalizes and bounds the operator identity", () => {
    const runtime = createRefrigerationLayoutRuntime({
      equipment: equipment(),
      mode: "demo",
      actorId: `  ${"x".repeat(200)}  `,
    });

    expect(runtime.actorId).toHaveLength(128);
    expect(runtime.actorId).toBe("x".repeat(128));
  });
});
