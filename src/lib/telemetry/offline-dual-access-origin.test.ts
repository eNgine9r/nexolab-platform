import { describe, expect, it } from "vitest";

import {
  resolveOfflineBrowserApiBaseUrl,
  resolveOfflineBrowserWebSocketUrl,
} from "./offline-dual-access-origin";

const API = "http://127.0.0.1:8082";
const WS = "ws://127.0.0.1:8082/api/v1/telemetry/live";

describe("explicit offline dual-browser origin contract", () => {
  it("preserves legacy config when not opted in", () => {
    const remote = { origin: "http://192.168.50.1:3000" };
    expect(resolveOfflineBrowserApiBaseUrl(API, undefined, remote)).toBe(API);
    expect(resolveOfflineBrowserWebSocketUrl(WS, "false", remote)).toBe(WS);
  });

  it("never derives server-side API hosts from request headers", () => {
    expect(resolveOfflineBrowserApiBaseUrl(API, "true", null)).toBe(API);
    expect(resolveOfflineBrowserWebSocketUrl(WS, "true", null)).toBe(WS);
  });

  it("keeps an attached Pi display on loopback", () => {
    expect(resolveOfflineBrowserApiBaseUrl(API, "true", { origin: "http://127.0.0.1:3000" })).toBe(API);
    expect(resolveOfflineBrowserWebSocketUrl(WS, "true", { origin: "http://127.0.0.1:3000" })).toBe(WS);
  });

  it.each(["192.168.50.1", "192.168.51.1", "172.26.0.10", "10.55.10.1"])(
    "uses the isolated Pi address %s for REST and WebSocket",
    (host) => {
      const location = { origin: `http://${host}:3000` };
      expect(resolveOfflineBrowserApiBaseUrl(API, "true", location)).toBe(`http://${host}:8082`);
      expect(resolveOfflineBrowserWebSocketUrl(WS, "true", location)).toBe(
        `ws://${host}:8082/api/v1/telemetry/live`,
      );
    },
  );

  it.each([
    "http://8.8.8.8:3000",
    "http://100.64.1.8:3000",
    "http://169.254.1.1:3000",
    "http://172.32.0.1:3000",
    "http://example.com:3000",
    "http://0.0.0.0:3000",
    "http://192.168.50.1:3001",
    "https://192.168.50.1:3000",
    "http://user:pass@192.168.50.1:3000",
    "http://[::1]:3000",
    "not a url",
  ])("fails closed on untrusted browser origin %s", (origin) => {
    expect(() => resolveOfflineBrowserApiBaseUrl(API, "true", { origin })).toThrow();
  });

  it.each([
    "http://172.18.48.66:8082",
    "http://127.0.0.1:8083",
    "https://127.0.0.1:8082",
    "http://127.0.0.1:8082/other",
    "http://127.0.0.1:8082/?token=bad",
    "http://user:pass@127.0.0.1:8082",
  ])("rejects non-pinned backend origin %s", (api) => {
    const remote = { origin: "http://192.168.50.1:3000" };
    expect(() => resolveOfflineBrowserApiBaseUrl(api, "true", remote)).toThrow(/pinned loopback/);
  });

  it("rejects an unexpected WebSocket path", () => {
    expect(() =>
      resolveOfflineBrowserWebSocketUrl("ws://127.0.0.1:8082/private", "true", {
        origin: "http://192.168.50.1:3000",
      }),
    ).toThrow(/pinned loopback/);
  });
});
