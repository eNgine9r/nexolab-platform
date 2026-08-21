import {
  createAuthenticatedFetch,
  type SecurityCredentialProvider,
} from "@/features/security/security-session";
import { createRuntimeCredentialProvider } from "@/features/security/supabase-auth";
import type { ClimateCatalogRepository } from "@/features/refrigeration/climate-catalog-repository";
import {
  createRefrigerationEquipmentRuntime,
  type RefrigerationEquipmentRuntimeInput,
} from "@/features/refrigeration/equipment-repository-runtime";
import type { RefrigerationEquipmentRepository } from "@/features/refrigeration/equipment-repository";
import { getTelemetryRuntimeConfig } from "@/lib/telemetry/runtime-config";

import { HttpEquipmentDiscoveryRepository, type EquipmentDiscoveryRepository } from "./discovery-repository";

export type EquipmentRegistryRuntime = {
  mode: "demo" | "live";
  equipmentRepository: RefrigerationEquipmentRepository | null;
  climateCatalogRepository: ClimateCatalogRepository | null;
  discoveryRepository: EquipmentDiscoveryRepository | null;
  error: string | null;
};

export function createEquipmentRegistryRuntime(
  input: RefrigerationEquipmentRuntimeInput = {},
): EquipmentRegistryRuntime {
  // Reuse the same authentication and organization-scoping primitives as the
  // canonical equipment repositories instead of creating a second auth model.
  const runtime = createRefrigerationEquipmentRuntime(input);
  let discoveryRepository: EquipmentDiscoveryRepository | null = null;
  if (runtime.mode === "live" && !runtime.error) {
    const apiBaseUrl = resolveApiBaseUrl(input);
    const organizationId = normalizeOrganizationId(
      input.organizationId ?? process.env.NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID,
    );
    if (apiBaseUrl) {
      const browserFetch = input.fetchImpl ?? fetch.bind(globalThis);
      const credentialProvider: SecurityCredentialProvider =
        input.credentialProvider ?? createRuntimeCredentialProvider(organizationId);
      discoveryRepository = new HttpEquipmentDiscoveryRepository({
        apiBaseUrl,
        fetchImpl: createAuthenticatedFetch(browserFetch, credentialProvider),
      });
    }
  }
  return {
    mode: runtime.mode,
    equipmentRepository: runtime.equipmentRepository,
    climateCatalogRepository: runtime.climateCatalogRepository ?? null,
    discoveryRepository,
    error: runtime.error,
  };
}

function resolveApiBaseUrl(input: RefrigerationEquipmentRuntimeInput): string | null {
  const explicit = input.apiBaseUrl?.trim();
  if (explicit) return explicit.replace(/\/+$/, "");
  const config = getTelemetryRuntimeConfig();
  return config.mode === "live" && config.apiBaseUrl ? config.apiBaseUrl.replace(/\/+$/, "") : null;
}

function normalizeOrganizationId(value: string | undefined): string | null {
  const normalized = value?.trim();
  return normalized ? normalized.slice(0, 128) : null;
}
