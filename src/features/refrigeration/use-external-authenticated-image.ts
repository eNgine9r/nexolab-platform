"use client";

import { useEffect, useState } from "react";

import type { EquipmentImageMetadata } from "@/data/refrigeration";
import { createAuthenticatedFetch } from "@/features/security/security-session";
import { createRuntimeCredentialProvider } from "@/features/security/supabase-auth";
import { isSameOrigin, resolvePublicApiBaseUrl } from "@/lib/runtime/public-endpoints";

/**
 * External staging and same-origin LAN mode (#1734): download private
 * S3-backed images via the protected Telemetry API with a bearer JWT; never
 * render private signed S3 URLs, whose host would be a private or former
 * address. Absolute-URL LAN builds and demo images keep their behaviour.
 */
export function useExternalAuthenticatedImage(
  equipmentId: string,
  image: EquipmentImageMetadata | null,
): string | null {
  const stageEnabled = process.env.NEXT_PUBLIC_NEXOLAB_EXTERNAL_HTTPS_STAGE === "true";
  const proxied = stageEnabled || isSameOrigin(process.env.NEXT_PUBLIC_NEXOLAB_API_BASE_URL);
  const [loaded, setLoaded] = useState<{ key: string; url: string } | null>(null);
  const imageId = image?.id ?? null;
  const originalUrl = image?.sourceUrl ?? null;
  const expectedMime = image?.mimeType ?? null;
  const imageKey = imageId ? `${equipmentId}:${imageId}` : null;

  useEffect(() => {
    if (!proxied || !imageId || imageId.startsWith("local-") || !expectedMime) {
      return;
    }
    const apiBaseUrl = resolvePublicApiBaseUrl();
    const controller = new AbortController();
    let ownedUrl: string | null = null;

    if (!apiBaseUrl) return;

    const load = async () => {
      try {
        const parsedBase = new URL(apiBaseUrl);
        if (
          (stageEnabled && parsedBase.protocol !== "https:") ||
          (parsedBase.protocol !== "https:" && parsedBase.protocol !== "http:") ||
          parsedBase.origin !== window.location.origin ||
          !["image/png", "image/jpeg", "image/webp"].includes(expectedMime)
        ) {
          return;
        }
        const target = new URL(
          `/api/v1/equipment/${encodeURIComponent(equipmentId)}/images/${encodeURIComponent(imageId)}/content`,
          parsedBase,
        );
        const fetchWithAuth = createAuthenticatedFetch(
          fetch.bind(globalThis),
          createRuntimeCredentialProvider(null),
        );
        const response = await fetchWithAuth(target.toString(), {
          signal: controller.signal,
          cache: "no-store",
          headers: { Accept: expectedMime },
        });
        if (!response.ok || response.headers.get("content-type")?.split(";")[0] !== expectedMime) {
          return;
        }
        // Never download unexpectedly large media from an external endpoint.
        const declaredLength = Number(response.headers.get("content-length") ?? "0");
        if (declaredLength > 16 * 1024 * 1024) return;
        const blob = await response.blob();
        if (controller.signal.aborted || blob.size > 16 * 1024 * 1024 || blob.type !== expectedMime) return;
        ownedUrl = URL.createObjectURL(blob);
        setLoaded({ key: `${equipmentId}:${imageId}`, url: ownedUrl });
      } catch {
        // Fail closed: no fallback to the private signed URL.
      }
    };
    void load();
    return () => {
      controller.abort();
      if (ownedUrl) URL.revokeObjectURL(ownedUrl);
    };
  }, [proxied, stageEnabled, equipmentId, imageId, expectedMime]);

  if (!image || !originalUrl) return null;
  if (!proxied || imageId?.startsWith("local-")) return originalUrl;
  return loaded?.key === imageKey ? loaded.url : null;
}
