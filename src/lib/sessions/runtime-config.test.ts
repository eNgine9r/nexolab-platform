import { afterEach, describe, expect, it, vi } from "vitest";

import { getSessionsApiBaseUrl } from "./runtime-config";

describe("getSessionsApiBaseUrl", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("rejects demo mode instead of returning synthetic sessions", () => {
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_DATA_MODE", "demo");

    expect(() => getSessionsApiBaseUrl()).toThrow(/Demo sessions are intentionally disabled/);
  });

  it("normalizes the configured live API URL", () => {
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_DATA_MODE", "live");
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_API_BASE_URL", "http://127.0.0.1:8082/root/?ignored=true#hash");

    expect(getSessionsApiBaseUrl()).toBe("http://127.0.0.1:8082/root");
  });

  it("rejects non-http protocols", () => {
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_DATA_MODE", "live");
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_API_BASE_URL", "ws://127.0.0.1:8082");

    expect(() => getSessionsApiBaseUrl()).toThrow(/HTTP or HTTPS/);
  });
});
