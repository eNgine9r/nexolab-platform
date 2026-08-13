import { HttpRefrigerationEquipmentRepository } from "@/features/refrigeration/equipment-repository";
import { HttpRefrigerationLayoutRepository } from "@/features/refrigeration/http-layout-repository";
import type { RefrigerationEquipmentRepository } from "@/features/refrigeration/equipment-repository";
import type { RefrigerationLayoutRepository } from "@/features/refrigeration/layout-repository";
import {
  createCachedLayoutRepository,
  createCachedRefrigerationEquipmentRepository,
} from "@/features/refrigeration/refrigeration-structural-cache";
import {
  createAuthenticatedFetch,
  type SecurityCredentialProvider,
} from "@/features/security/security-session";
import { createRuntimeCredentialProvider } from "@/features/security/supabase-auth";
import { getTelemetryRuntimeConfig } from "@/lib/telemetry/runtime-config";

export type EquipmentLayoutsRuntime = {
  mode: "demo" | "live";
  equipmentRepository: RefrigerationEquipmentRepository | null;
  layoutRepository: RefrigerationLayoutRepository | null;
  cacheScope: string | null;
  error: string | null;
};

export type EquipmentLayoutsRuntimeInput = {
  fetchImpl?: typeof fetch;
  credentialProvider?: SecurityCredentialProvider;
  organizationId?: string | null;
  mode?: string;
  apiBaseUrl?: string;
};

export function createEquipmentLayoutsRuntime(
  input: EquipmentLayoutsRuntimeInput = {},
): EquipmentLayoutsRuntime {
  try {
    const config = runtimeConfig(input);
    if (config.mode === "demo") {
      return {
        mode: "demo",
        equipmentRepository: null,
        layoutRepository: null,
        cacheScope: null,
        error: "Каталог схем доступний лише в live mode і не підміняє відсутній API демонстраційними даними.",
      };
    }

    const organizationId = normalizeOrganizationId(input.organizationId);
    const browserFetch = input.fetchImpl ?? fetch.bind(globalThis);
    const credentialProvider = input.credentialProvider ?? createRuntimeCredentialProvider(organizationId);
    const authenticatedFetch = createAuthenticatedFetch(browserFetch, credentialProvider);
    const cacheScope = `${config.apiBaseUrl}|${organizationId ?? "default"}`;

    return {
      mode: "live",
      equipmentRepository: createCachedRefrigerationEquipmentRepository(
        new HttpRefrigerationEquipmentRepository({
          apiBaseUrl: config.apiBaseUrl,
          fetchImpl: authenticatedFetch,
        }),
        cacheScope,
      ),
      layoutRepository: createCachedLayoutRepository(
        new HttpRefrigerationLayoutRepository({
          apiBaseUrl: config.apiBaseUrl,
          fetchImpl: authenticatedFetch,
        }),
        cacheScope,
      ),
      cacheScope,
      error: null,
    };
  } catch (error) {
    return {
      mode: input.mode === "live" ? "live" : "demo",
      equipmentRepository: null,
      layoutRepository: null,
      cacheScope: null,
      error: error instanceof Error ? error.message : "Не вдалося налаштувати каталог схем обладнання.",
    };
  }
}

function runtimeConfig(
  input: EquipmentLayoutsRuntimeInput,
): { mode: "demo"; apiBaseUrl: null } | { mode: "live"; apiBaseUrl: string } {
  if (input.mode !== undefined || input.apiBaseUrl !== undefined) {
    const mode = input.mode?.trim() || "demo";
    if (mode === "demo") return { mode: "demo", apiBaseUrl: null };
    if (mode !== "live") throw new Error(`Unsupported equipment layouts mode: ${mode}`);
    const apiBaseUrl = input.apiBaseUrl?.trim();
    if (!apiBaseUrl) throw new Error("NEXOLAB API URL is required for equipment layouts.");
    return { mode: "live", apiBaseUrl };
  }

  const config = getTelemetryRuntimeConfig();
  if (config.mode === "demo") return { mode: "demo", apiBaseUrl: null };
  if (!config.apiBaseUrl) throw new Error("NEXOLAB API URL is required for equipment layouts.");
  return { mode: "live", apiBaseUrl: config.apiBaseUrl };
}

function normalizeOrganizationId(value: string | null | undefined): string | null {
  const normalized = value?.trim();
  return normalized ? normalized.slice(0, 128) : null;
}
