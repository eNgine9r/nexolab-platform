import { describe, expect, it } from "vitest";

import { buildSettingsRuntimeDiagnostics, sanitizeEndpoint } from "./runtime-diagnostics";

describe("settings runtime diagnostics", () => {
  it("removes credentials, query strings and fragments from displayed endpoints", () => {
    const endpoint = sanitizeEndpoint(
      "https://operator:secret@lab.local:8082/api/v1?token=top-secret#fragment",
      "api",
      ["http:", "https:"],
    );

    expect(endpoint.valid).toBe(true);
    expect(endpoint.displayValue).toBe("https://lab.local:8082/api/v1");
    expect(endpoint.redactions).toEqual(["credentials", "query", "fragment"]);
    expect(JSON.stringify(endpoint)).not.toContain("operator");
    expect(JSON.stringify(endpoint)).not.toContain("top-secret");
  });

  it("returns an explicit unsafe state for invalid URLs without throwing", () => {
    const diagnostics = buildSettingsRuntimeDiagnostics({
      profile: "LOCAL_LAN",
      dataMode: "live",
      authProvider: "local",
      apiBaseUrl: "not-an-absolute-url",
      websocketUrl: "ws://127.0.0.1:8082/api/v1/telemetry/live",
      browserOrigin: "http://127.0.0.1:3000",
    });

    expect(diagnostics.status).toBe("unsafe");
    expect(diagnostics.api.valid).toBe(false);
    expect(diagnostics.issues.map((issue) => issue.code)).toContain("INVALID_API_URL");
  });

  it("classifies missing live endpoints as incomplete", () => {
    const diagnostics = buildSettingsRuntimeDiagnostics({
      profile: "LOCAL_LAN",
      dataMode: "live",
      authProvider: "local",
      browserOrigin: "http://127.0.0.1:3000",
    });

    expect(diagnostics.status).toBe("incomplete");
    expect(diagnostics.issues.map((issue) => issue.code)).toEqual(
      expect.arrayContaining(["MISSING_API_URL", "MISSING_WEBSOCKET_URL"]),
    );
  });

  it("detects HTTPS dashboard mixed content", () => {
    const diagnostics = buildSettingsRuntimeDiagnostics({
      profile: "LOCAL_LAN",
      dataMode: "live",
      authProvider: "local",
      apiBaseUrl: "http://central.local:8082",
      websocketUrl: "ws://central.local:8082/api/v1/telemetry/live",
      browserOrigin: "https://dashboard.local",
    });

    expect(diagnostics.status).toBe("unsafe");
    expect(diagnostics.issues.map((issue) => issue.code)).toContain("MIXED_CONTENT");
  });

  it("accepts a sanitized LOCAL_LAN live configuration and custom test provider", () => {
    const diagnostics = buildSettingsRuntimeDiagnostics({
      profile: "LOCAL_LAN",
      dataMode: "live",
      authProvider: "acceptance",
      apiBaseUrl: "http://127.0.0.1:18102",
      websocketUrl: "ws://127.0.0.1:18102/api/v1/telemetry/live",
      browserOrigin: "http://127.0.0.1:13020",
    });

    expect(diagnostics.status).toBe("ready");
    expect(diagnostics.authProvider).toBe("custom");
    expect(diagnostics.authProviderLabel).toBe("acceptance");
    expect(diagnostics.api.displayValue).toBe("http://127.0.0.1:18102");
    expect(diagnostics.websocket.displayValue).toBe(
      "ws://127.0.0.1:18102/api/v1/telemetry/live",
    );
  });

  it("marks secret material in public runtime URLs as unsafe while keeping output sanitized", () => {
    const diagnostics = buildSettingsRuntimeDiagnostics({
      profile: "LOCAL_LAN",
      dataMode: "live",
      authProvider: "local",
      apiBaseUrl: "http://user:password@127.0.0.1:8082?access_token=secret-value",
      websocketUrl: "ws://127.0.0.1:8082/api/v1/telemetry/live#secret-fragment",
      browserOrigin: "http://127.0.0.1:3000",
    });
    const serialized = JSON.stringify(diagnostics);

    expect(diagnostics.status).toBe("unsafe");
    expect(diagnostics.issues.map((issue) => issue.code)).toContain("PUBLIC_URL_SECRET_MATERIAL");
    expect(serialized).not.toContain("password");
    expect(serialized).not.toContain("secret-value");
    expect(serialized).not.toContain("secret-fragment");
  });
});
