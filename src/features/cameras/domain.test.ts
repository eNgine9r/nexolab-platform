import { describe, expect, it } from "vitest";

import { parseCameraInventory, sanitizeCameraEndpoint } from "./domain";

describe("sanitizeCameraEndpoint", () => {
  it("keeps only local origin and path", () => {
    expect(sanitizeCameraEndpoint("http://192.168.1.20/snapshot.jpg?token=secret#frame")).toBe(
      "http://192.168.1.20/snapshot.jpg",
    );
  });

  it("rejects credentials and public endpoints", () => {
    expect(sanitizeCameraEndpoint("rtsp://admin:secret@192.168.1.20/live")).toBeNull();
    expect(sanitizeCameraEndpoint("https://camera.example.com/live")).toBeNull();
  });
});

describe("parseCameraInventory", () => {
  it("rejects incomplete entries", () => {
    expect(parseCameraInventory([{ id: "CAM-01" }, null])).toEqual({ items: [], rejected: 2 });
  });

  it("marks unsafe endpoints invalid", () => {
    const result = parseCameraInventory([
      {
        id: "CAM-01",
        name: "Laboratory",
        endpoint: "rtsp://operator:secret@10.0.0.10/live",
        sourceKind: "rtsp",
        state: "configured",
      },
    ]);

    expect(result.items[0]).toMatchObject({
      endpoint: null,
      state: "invalid",
    });
  });

  it("does not allow raw RTSP configuration to claim browser online", () => {
    const result = parseCameraInventory([
      {
        id: "CAM-02",
        name: "Warehouse",
        endpoint: "rtsp://10.0.0.11/live",
        sourceKind: "rtsp",
        state: "online",
        capabilities: ["stream"],
      },
    ]);

    expect(result.items[0]).toMatchObject({
      state: "unavailable",
      reason: "Raw RTSP is not a browser playback contract.",
    });
  });
});
