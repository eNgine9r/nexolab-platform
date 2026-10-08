"use client";

import { useEffect, useState } from "react";

import type { EquipmentImageMetadata } from "@/data/refrigeration";
import { createAuthenticatedFetch } from "@/features/security/security-session";
import { createRuntimeCredentialProvider } from "@/features/security/supabase-auth";

/**
 * External staging only: download private S3-backed images via the protected
 * Telemetry API with a bearer JWT; never render private signed S3 URLs.
 * No change to the approved LAN image handling or demo images.
 */
export function useExternalAuthenticatedImage(
  equipmentId: string,
  image: EquipmentImageMetadata | null,
): string | null {
  const stageEnabled = process.env.NEXT_PUBLIC_NEXOLAB_EXTERNAL_HTTPS_STAGE === "true";
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const imageId = image?.id ?? null;
  const originalUrl = image?.sourceUrl ?? null;
  const expectedMime = image?.mimeType ?? null;

  useEffect(() => {
    if (!stageEnabled || !imageId || imageId.startsWith("local-") || !expectedMime) {
      return;
    }
    const apiBaseUrl = process.env.NEXT_PUBLIC_NEXOLAB_API_BASE_URL?.trim();
    const controller = new AbortController();
    let ownedUrl: string | null = null;
    setObjectUrl(null);

    if (!apiBaseUrl) return;

    const load = async () => {
      try {
        const parsedBase = new URL(apiBaseUrl);
        if (
          parsedBase.protocol !== "https:" ||
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
        setObjectUrl(ownedUrl);
      } catch {
        // Fail closed: no fallback to the private signed URL.
      }
    };
    void load();
    return () => {
      controller.abort();
      if (ownedUrl) URL.revokeObjectURL(ownedUrl);
    };
  }, [stageEnabled, equipmentId, imageId, expectedMime]);

  if (!image || !originalUrl) return null;
  if (!stageEnabled || imageId?.startsWith("local-")) return originalUrl;
  return objectUrl;
}
