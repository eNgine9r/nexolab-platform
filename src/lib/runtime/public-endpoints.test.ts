import { describe, expect, it } from "vitest";

import { isSameOrigin, resolvePublicApiBaseUrl, resolvePublicWebSocketUrl } from "./public-endpoints";

const lanHttp = { protocol: "http:", host: "192.168.1.220:3000", origin: "http://192.168.1.220:3000" };
const wifiName = {
  protocol: "http:",
  host: "nexolab-edge-01.local:3000",
  origin: "http://nexolab-edge-01.local:3000",
};
const tailnet = { protocol: "https:", host: "edge.example.ts.net", origin: "https://edge.example.ts.net" };

describe("public endpoints", () => {
  it("keeps absolute URLs unchanged", () => {
    expect(resolvePublicApiBaseUrl("http://10.0.0.5:8082", lanHttp)).toBe("http://10.0.0.5:8082");
    expect(resolvePublicWebSocketUrl("ws://10.0.0.5:8082/api/v1/telemetry/live", lanHttp)).toBe(
      "ws://10.0.0.5:8082/api/v1/telemetry/live",
    );
  });

  it("resolves same-origin from whatever address or name served the page", () => {
    expect(resolvePublicApiBaseUrl("same-origin", lanHttp)).toBe("http://192.168.1.220:3000");
    expect(resolvePublicApiBaseUrl(" same-origin ", wifiName)).toBe("http://nexolab-edge-01.local:3000");
    expect(resolvePublicWebSocketUrl("same-origin", lanHttp)).toBe(
      "ws://192.168.1.220:3000/api/v1/telemetry/live",
    );
  });

  it("uses wss behind HTTPS", () => {
    expect(resolvePublicApiBaseUrl("same-origin", tailnet)).toBe("https://edge.example.ts.net");
    expect(resolvePublicWebSocketUrl("same-origin", tailnet)).toBe(
      "wss://edge.example.ts.net/api/v1/telemetry/live",
    );
  });

  it("does not resolve same-origin without a browser location or for other schemes", () => {
    expect(resolvePublicApiBaseUrl("same-origin", null)).toBeUndefined();
    expect(resolvePublicWebSocketUrl("same-origin", null)).toBeUndefined();
    expect(
      resolvePublicApiBaseUrl("same-origin", { protocol: "file:", host: "", origin: "null" }),
    ).toBeUndefined();
  });

  it("treats unset values as unset", () => {
    expect(resolvePublicApiBaseUrl(undefined, lanHttp)).toBeUndefined();
    expect(resolvePublicApiBaseUrl("  ", lanHttp)).toBeUndefined();
    expect(isSameOrigin(" same-origin")).toBe(true);
    expect(isSameOrigin("http://same-origin")).toBe(false);
  });
});
