import { afterEach, describe, expect, it, vi } from "vitest";

import { getRefrigerationEquipment } from "@/data/refrigeration";

import { createRefrigerationLayoutRuntime } from "./layout-repository-runtime";
import { InMemoryRefrigerationLayoutRepository } from "./layout-repository";

function equipment() {
  const value = getRefrigerationEquipment("showcase-106-01");
  if (!value) throw new Error("Refrigeration fixture is missing");
  return value;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

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

  it("uses the cached production repository contract in live mode", () => {
    const runtime = createRefrigerationLayoutRuntime({
      equipment: equipment(),
      mode: "live",
      apiBaseUrl: "http://127.0.0.1:8082",
      actorId: "operator-live",
    });

    expect(runtime.mode).toBe("live");
    expect(runtime.repository).toMatchObject({
      getDraft: expect.any(Function),
      getPublished: expect.any(Function),
      saveDraft: expect.any(Function),
      publishDraft: expect.any(Function),
      listHistory: expect.any(Function),
      restoreRevision: expect.any(Function),
      uploadImage: expect.any(Function),
    });
    expect(runtime.actorId).toBe("operator-live");
    expect(runtime.error).toBeNull();
  });

  it("binds the native browser fetch receiver in live mode", async () => {
    const fetchSpy = vi.fn(function (this: unknown) {
      if (this !== globalThis) throw new TypeError("Illegal invocation");
      return Promise.resolve(
        new Response(
          JSON.stringify({
            id: "draft-1",
            equipment_id: equipment().id,
            version: 1,
            image: null,
            placements: [],
            created_at: "2026-07-25T00:00:00.000Z",
            updated_at: "2026-07-25T00:00:00.000Z",
          }),
          {
            headers: {
              "Content-Type": "application/json",
              ETag: 'W/"layout-draft-v1"',
            },
          },
        ),
      );
    }) as unknown as typeof fetch;
    vi.stubGlobal("fetch", fetchSpy);

    const runtime = createRefrigerationLayoutRuntime({
      equipment: equipment(),
      mode: "live",
      apiBaseUrl: "http://127.0.0.1:8082",
    });
    const draft = await runtime.repository?.getDraft(equipment().id);

    expect(fetchSpy).toHaveBeenCalledOnce();
    expect(draft).toMatchObject({ ok: true, value: { version: 1 } });
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
