// @vitest-environment jsdom
// @vitest-environment-options {"url":"https://nexolab.example.test/"}

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

const PRIVATE_S3 = "http://172.18.48.66:9000/equipment-images/private.png";
const image = {
  id: "image-123",
  mimeType: "image/png",
  sourceUrl: PRIVATE_S3,
} as EquipmentImageMetadata;

describe("external authenticated photo rendering", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_API_BASE_URL", "https://nexolab.example.test");
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_EXTERNAL_HTTPS_STAGE", "true");
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:secure") });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("never falls back to signed private S3 URL when staged fetch is denied", async () => {
    fetchMock.mockResolvedValue({ ok: false, headers: new Headers(), status: 403 });
    const { result } = renderHook(() => useExternalAuthenticatedImage("equipment-1", image));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(result.current).toBeNull();
    expect(fetchMock.mock.calls[0][0]).toBe(
      "https://nexolab.example.test/api/v1/equipment/equipment-1/images/image-123/content",
    );
    expect(fetchMock.mock.calls[0][0]).not.toContain("172.18.48.66");
  });

  it("rejects a cross-origin HTTPS configuration before making any request", async () => {
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_API_BASE_URL", "https://untrusted.example.test");
    const { result } = renderHook(() => useExternalAuthenticatedImage("equipment-1", image));
    expect(result.current).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("creates an in-memory blob URL only after successful protected response and revokes it", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      headers: new Headers({ "content-type": "image/png", "content-length": "4" }),
      blob: async () => new Blob(["test"], { type: "image/png" }),
    });
    const { result, unmount } = renderHook(() => useExternalAuthenticatedImage("equipment-1", image));
    await waitFor(() => expect(result.current).toBe("blob:secure"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ cache: "no-store" });
    unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:secure");
  });

  it("preserves existing LAN image source without fetching in non-external mode", () => {
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_EXTERNAL_HTTPS_STAGE", "false");
    const { result } = renderHook(() => useExternalAuthenticatedImage("equipment-1", image));
    expect(result.current).toBe(PRIVATE_S3);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
