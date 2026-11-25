// @vitest-environment jsdom
// @vitest-environment-options {"url":"http://192.168.1.220:3000/refrigeration"}

import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EquipmentImageMetadata } from "@/data/refrigeration";

import { useExternalAuthenticatedImage } from "./use-external-authenticated-image";

vi.mock("@/features/security/security-session", () => ({
  createAuthenticatedFetch: () => fetch.bind(globalThis),
}));
vi.mock("@/features/security/supabase-auth", () => ({
  createRuntimeCredentialProvider: () => async () => ({ accessToken: "test-only" }),
}));

const FORMER_ADDRESS_S3 = "http://172.18.48.66:9000/equipment-images/private.png";
const image = {
  id: "image-123",
  mimeType: "image/png",
  sourceUrl: FORMER_ADDRESS_S3,
} as EquipmentImageMetadata;

describe("same-origin LAN photo rendering (#1734)", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_API_BASE_URL", "same-origin");
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_EXTERNAL_HTTPS_STAGE", "false");
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:lan") });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("loads the photo through the API on the page origin, never the signed storage URL", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      headers: new Headers({ "content-type": "image/png", "content-length": "4" }),
      blob: async () => new Blob(["test"], { type: "image/png" }),
    });
    const { result } = renderHook(() => useExternalAuthenticatedImage("equipment-1", image));
    await waitFor(() => expect(result.current).toBe("blob:lan"));
    expect(fetchMock.mock.calls[0][0]).toBe(
      "http://192.168.1.220:3000/api/v1/equipment/equipment-1/images/image-123/content",
    );
  });

  it("shows nothing rather than the private storage URL when the API refuses", async () => {
    fetchMock.mockResolvedValue({ ok: false, headers: new Headers(), status: 403 });
    const { result } = renderHook(() => useExternalAuthenticatedImage("equipment-1", image));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(result.current).toBeNull();
  });

  it("keeps absolute-URL LAN builds unchanged", () => {
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_API_BASE_URL", "http://10.0.0.5:8082");
    const { result } = renderHook(() => useExternalAuthenticatedImage("equipment-1", image));
    expect(result.current).toBe(FORMER_ADDRESS_S3);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
